from collections.abc import Collection
import abc
import dataclasses
import datetime
import enum
import re
from types import MappingProxyType
from typing import Callable, ClassVar, Mapping
from pathlib import Path, PurePosixPath
import tomllib

import dateutil.tz

import grading_sheet.config as grading_sheet_config
import util.enum
import util.gdpr_coding
import util.general
import util.markdown
import util.print_parse
import util.url
import gitlab_.tools
import chalmers_pdb

from util.print_parse import PrinterParser


class RequestMatcher:
    """
    Interface defining a matcher for request tag names.

    Required attributes:
    * protection_patterns:
        An iterable collection of wildcard pattern used to protect request tags
        on GitLab Chalmers from modification by developers (students).
        The union of these patterns must cover all strings for which the match method returns True.

    TODO once GitLab implements regex patterns for tag protection: replace interface by a single regex.
    """

    @abc.abstractmethod
    def parse(self, tag):
        """
        Determines whether the given tag name matches this request matcher.
        If it matches, returns an implementation-specific value different from None.
        Otherwise, returns None.

        Tags with name containing the path component separator '/' are never considered as requests.
        They are sorted out before this method is called.
        """


class RegexRequestMatcher(RequestMatcher):
    def __init__(self, protection_patterns, regex, regex_flags=0):
        """
        Build a request matcher from a specified regex.

        Arguments:
        * protection:
            Iterable of wildcard pattern used to protect request tags
            from modification by students.
        * regex:
            Regex with which to match the request tag.
        * regex_flags:
            Flags to use for regex matching.
        """
        self.protection_patterns = list(protection_patterns)
        self._regex = regex
        self._regex_flags = regex_flags

    def parse(self, tag):
        return re.fullmatch(self._regex, tag, self._regex_flags)


class RequestHandler:
    """
    This interface specifies a request handler.
    A request handler matches some requests (tags in lab group repository)
    as specified by its associated request matcher.
    For any unhandled request, the lab instance calls
    the request handler via the 'handle_request' method.
    The request handler must then handle the request
    in some implementation-defined manner.
    For example, it may post response issues for the lab instance.

    Required attributes:
    * request_matcher:
        The request matcher to be used for this type of request.
    * response_titles:
        Return a dictionary whose values are printer-parsers for issue titles.
        Its values should be string-convertible.
        The request handler may only produce response issues by calling
        a method in the lab instance that produces it via a key
        to the dictionary of issue title printer-parsers.
        If this attribute is provided dynamically, its keys must be stable.
        The attribute must be stable after setup has been called.

        The domains of the printer-parsers are string-valued dictionaries
        that must include the key 'tag' for the name of the associated request.

    Required for multi-variant labs:
    * variant_failure_key:
        Key in self.response_titles identifying variant detection failure issues.
        If there is not a unique problem commit ancestor, the lab system rejects the submission with such an issue.
        This happens before the request handler handles the request.

        Its associated issue-title printer-parser must have printer-parser with domain ditionaries containing no extra keys.

        If this attribute does not exist or is None, it is up to the request handler to deal with variant detection failure.
        For this, use the list request_and_responses.variants of detected variant candidates.
    """

    def setup(self, lab):
        """
        Setup this testing handler.
        Called by the Lab class before any other method is called.
        """
        # TODO: design better architecture that avoids these late assignments.
        # pylint: disable-next=attribute-defined-outside-init
        self.lab = lab

    @abc.abstractmethod
    def handle_request(self, request_and_responses):
        """
        Handle a testing request.
        Takes an instance of group_project.request_and_responses as argument.

        This method may call request_and_responses for the following:
        * Work with the git repository for any tag under tag_name.
          This may read tags and create new tagged commits.
          Use methods (TODO) of the lab instance to work with this as a cache.
        * Make calls to response issue posting methods (TODO) of the lab instance.

        After calling this method, the lab instance will create
        a tag <group-id>/<tag_name>/handled to mark the request as handled.
        This method may return a JSON-dumpable value.
        If so, its dump will be stored as the message of the above tag.
        """


class SubmissionHandler(RequestHandler):
    # pylint: disable=abstract-method
    """
    This interface specifies a request handler for handling submissions.

    Required attributes (in addition to the ones of RequestHandler):

    * review_response_key
        Key in self.response_titles identifying submissions review issues (produced by graders).
        These are also known as "grading issues".

        Submission review issues must have printer-parser
        with domain a dictionary containing a key 'outcome'.
        The type of its value is specific to the submission handler.
        It must be JSON-encodable (combination of dict, list, and primitive types).

        To not set up review issues, set review_response_key to None.
        In that case, the only possible grading pathway
        is via the result of the submission handler.

    * grading_columns
        Customized columns for the live submissions table.
        A collection of instances of live_submissions_table.Column.

    The handle_request method must returns a JSON-encodable dictionary.
    This dictionary must have the following key:

    - 'accepted':
        Boolean indicating if the submission system
        should accept or reject the submission.

        Note that this is different from passing and failing.
        A rejected submission does not count as an actual submission.
        This is important if only a certain number of submissions are allowed,
        or a valid submission is required before a certain date.

    - 'review_needed' (if 'accepted' is True):
        Boolean indicating if the handler wants a grader to
        take a look at the submission and decide its outcome.

    - 'outcome_response_key' (if 'accepted' is True and 'review_needed' is False):
        Response key of the response issue posted by the submission handler
        that notifies the students of their submission outcome.

        The associated issue title printer-parser needs to have domain
        a dictionary with an 'outcome' entry as for a submission review issue.
        Existing review issues always override the submission outcome
        of the submission handler, even if 'review_needed' is not True.
    """


class HandlingException(Exception, util.markdown.Markdown):
    # pylint: disable=abstract-method
    """
    Raised for errors caused by a problems with a submission.
    Should be reportable in issues in student repositories.
    """


@dataclasses.dataclass(frozen=True, kw_only=True)
class TimeConfig:
    """Time printing configuration."""

    @classmethod
    def timezone_default(cls) -> datetime.tzinfo:
        r = dateutil.tz.gettz("Europe/Stockholm")
        assert r is not None
        return r

    zone: datetime.tzinfo = dataclasses.field(
        # pylint: disable-next=unnecessary-lambda
        default_factory=lambda: TimeConfig.timezone_default()
    )
    """Timezone to use."""

    format: str = "%b %d %H:%M %Z"
    """Format string to use."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class GitlabConfig:
    """General configuration for Chalmers GitLab."""

    url: util.url.URL = util.url.url_formatter.parse("https://git.chalmers.se")
    """Base URL of Chalmers GitLab."""

    web_netloc: util.url.NetLoc = util.url.NetLoc(host="git.chalmers.se", port=443)
    """
    Net location of the web server of Chalmers GitLab.

    TODO: derive from url.
    """

    ssh_use_multiplexer: bool = True
    """
    Whether to use a multiplexer to share a single SSH connection for multiple remote git operations.
    Recommended as it speeds things up considerably.
    Also, SSH connections to git.chalmers.se from outside the Chalmers network are subject to strict rate limiting.
    """

    ssh_netloc: util.url.NetLoc = util.url.NetLoc(host="git.chalmers.se", user="git")
    """Usually, the host is shared with web_netloc and the user is 'git'."""

    ssh_max_sessions: int = 5
    """
    Maximum number of parallel jobs to use for git fetches and pushes.
    The sshd config for Chalmers GitLab seems to have MaxSessions=5 (checked 2021-12).
    """

    lab_system_users: Collection[str] = frozenset({"lab-system"})
    """Usernames on Chalmers GitLab that are recognized as acting as the lab system."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class GroupSetConfig[GroupId]:
    """
    Configuration of a group set.
    Specifies integration with:
    * Canvas group set,
    * lab group folder on Chalmers Gitlab,
    * formatting in live submissions table,
    * pasting and formatting in overview grading sheet.

    The default values only make sense for integer group ids.
    """

    id: PrinterParser[GroupId, int | str] = util.print_parse.int_str()
    """
    Human-readable id.
    Typical use case: values in a column of group identifiers.
    Used by default in the grading sheet and the live submission table.
    """

    full_id: PrinterParser[GroupId, str] = util.print_parse.regex_int("group-{}")
    """
    Used for group project paths.
    Used as part of tag names in collection repository.
    Note that many special characters are forbidden in GitLab group names.
    """

    name: PrinterParser[GroupId, str] = util.print_parse.regex_int(
        "Lab group {}",
        flags=re.IGNORECASE,
    )
    """
    Full human-readable name.
    Used in Canvas group set.
    Why not use use a zero-based numerical naming scheme:
    * Lab group 0,
    * Lab group 1,
    * ...?
    """

    group_set_name: str = "Lab groups"
    """
    Name of the group set on Canvas.
    Students sign up for lab groups here.
    """

    gdpr_coding: util.gdpr_coding.GDPRCoding = util.gdpr_coding.GDPRCoding(
        identifier=util.print_parse.on_parse(int)
    )
    """
    How to pseudonymously format and sort group identifiers.
    To be used in situations that are not GDPR cleared.

    Must raise an exception on formatted string not plausibly corresponding to a group.
    This is needed for parsing the grading spreadsheet.
    """


DefaultGroupId = int


@dataclasses.dataclass(frozen=True, kw_only=True)
class OutcomeSpec:
    name: str
    label: gitlab_.tools.LabelSpec | None = None
    as_cell: str | int = str()
    canvas_grade: int | None = None

    @classmethod
    def smart(
        cls,
        name: str,
        color: str | None = None,
        as_cell: str | int = str(),
        canvas_grade: int | None = None,
    ) -> "OutcomeSpec":
        return cls(
            name=name,
            label=(
                None
                if color is None
                else gitlab_.tools.LabelSpec(name=name, color=color)
            ),
            as_cell=as_cell,
            canvas_grade=canvas_grade,
        )


class DefaultOutcome(util.enum.EnumSpec[OutcomeSpec]):
    INCOMPLETE = OutcomeSpec.smart(
        name="incomplete",
        color="red",
        as_cell=0,
        canvas_grade=0,
    )
    PASS = OutcomeSpec.smart(
        name="pass",
        color="green",
        as_cell=1,
        canvas_grade=1,
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class OutcomesConfig[Outcome]:
    """
    Configuration of grading outcomes in a lab.
    Most easily built using the smart constructor OutcomesConfig.smart.
    See OutcomesConfig.default_outcome_specs for its default argument.
    """

    outcomes: Collection[Outcome]
    """The set of possible outcomes."""

    name: PrinterParser[Outcome, str]
    """Formats an outcome as a student-readable string."""

    as_cell: PrinterParser[Outcome, int | str]
    """Formats the outcome for use in a spreadsheet cell."""

    labels: Mapping[Outcome | None, gitlab_.tools.LabelSpec]
    """
    Labels to use for outcomes in new-style grading via merge requests.
    The label specification for key None corresponds to the waiting-for-grading state.
    """

    canvas_grade: Mapping[Outcome, int | None]
    """
    Mapping from outcomes to grades in a Canvas assignment.
    A value of None corresponds to a missing grade.
    Use this if you do not want failing grades to show up on Canvas.
    """

    default_waiting_for_grading: ClassVar[OutcomeSpec] = OutcomeSpec.smart(
        "waiting-for-grading", "yellow"
    )

    @classmethod
    def from_mapping(
        cls,
        outcomes: Mapping[Outcome, OutcomeSpec],
        waiting_for_grading: OutcomeSpec = default_waiting_for_grading,
    ) -> "OutcomesConfig[Outcome]":
        """
        Smart constructor.
        Assumes the names are in lower case.
        """
        return cls(
            outcomes=frozenset(outcomes.keys()),
            name=util.print_parse.compose(
                util.print_parse.Dict(
                    (outcome, spec.name)
                    for outcome, spec in outcomes.items()
                    if outcome is not None
                ),
                util.print_parse.on_parse(str.lower),
            ),
            as_cell=util.print_parse.Dict(
                (outcome, spec.as_cell) for outcome, spec in outcomes.items()
            ),
            labels={outcome: spec.label for outcome, spec in outcomes.items()}
            | {None: waiting_for_grading.label},
            canvas_grade={
                outcome: spec.canvas_grade for outcome, spec in outcomes.items()
            },
        )

    @classmethod
    def from_enum_spec[X: util.enum.EnumSpec[OutcomeSpec]](
        cls: "type[OutcomesConfig[X]]",
        enum_spec: type[X] = DefaultOutcome,
        waiting_for_grading: OutcomeSpec = default_waiting_for_grading,
    ) -> "OutcomesConfig[X]":
        """
        Smart constructor.
        Takes a specification enumeration.
        See from_mapping for remaining arguments.
        """
        return cls.from_mapping(
            {value: value.value for value in enum_spec},
            waiting_for_grading=waiting_for_grading,
        )


class StandardVariant(enum.Enum):
    """Variant type for a lab without variants."""

    UNIQUE = enum.auto()


@dataclasses.dataclass(frozen=True, kw_only=True)
class VariantSpec:
    name: str
    branch: str

    @classmethod
    def smart(cls, name: str) -> "VariantSpec":
        """
        Smart constructor.
        Name should match "[a-zA-Z ]*"
        Branch is dashification of name.
        """
        return cls(name=name, branch=util.general.dashify(name))


@dataclasses.dataclass(frozen=True, kw_only=True)
class VariantsConfig[Variant]:
    """
    Configuration of lab variants.
    These are typically used for multi-language labs.
    Labs have different problem and submission branches for each lab variant.
    The students can choose which variant to work with.
    """

    variants: Collection[Variant]
    """
    The available lab variants.
    A singleton set containing the empty tuple denotes a variants-free lab.
    See VariantsConfig.no_variants.
    """

    default: Variant
    """
    The default lab variant.
    Used for the main branches in student repositories.
    """

    serialize: PrinterParser[Variant, util.general.JSON]
    """Serializes a variant."""

    name: PrinterParser[Variant, str]
    """Formats a variant as a student-readable string."""

    branch: Callable[[str, Variant], str]
    """
    The branch for a branch kind and variant.
    For example: ("problem", "java") may become "problem-java".
    """

    source: Callable[[str, Variant], Path]
    """
    Obtain the path of the sources for a branch and variant.
    This is relative to the path of the lab.
    For example: ("problem", "java") may become Path("problem", "java").
    """

    submission_grading_title: PrinterParser[Variant, str]
    """
    Format a variant as a title for a submission grading.
    For example: "java" may become "Grading for Java submission".
    Used for grading merge requests.
    """

    def __bool__(self) -> bool:
        """Checks whether variants are configured."""
        return not self.variants != set(StandardVariant)

    @classmethod
    def no_variants(
        cls: "type[VariantsConfig[StandardVariant]]",
        submission_grading_title: str = "Grading for submission",
    ) -> "VariantsConfig[StandardVariant]":
        """Smart constuctor for a variant-free lab."""

        def branch(branch: str, _: StandardVariant) -> str:
            return branch

        def source(branch: str, _: StandardVariant) -> Path:
            return Path(branch)

        return cls(
            variants=frozenset(StandardVariant),
            default=StandardVariant.UNIQUE,
            serialize=util.print_parse.Dict([(StandardVariant.UNIQUE, None)]),
            name=util.print_parse.Dict(
                [(StandardVariant.UNIQUE, "<standard variant>")]
            ),
            branch=branch,
            source=source,
            submission_grading_title=util.print_parse.Dict(
                [(StandardVariant.UNIQUE, submission_grading_title)]
            ),
        )

    default_submission_grading_title_holed = "Grading for {} submission"
    default_name_key = str.lower

    @classmethod
    def from_mapping(
        cls,
        variants: Mapping[Variant, VariantSpec],
        default: Variant | None = None,
        submission_grading_title_holed: str = default_submission_grading_title_holed,
        name_key: Callable[[str], str] = default_name_key,
    ) -> "VariantsConfig[Variant]":
        """
        Smart constructor with sensible defaults.
        If the default is not specified, it defaults to the first entry of 'variants'.
        The name_key argument is used for normalizing names.
        It should be injective on names.
        """
        if default is None:
            default = list(variants.keys())[0]

        name = util.print_parse.compose(
            util.print_parse.Dict((v, spec.name) for v, spec in variants.items()),
            util.print_parse.on_parse_normalize(
                (spec.name for spec in variants.values()),
                name_key,
            ),
        )
        branch_part = util.print_parse.Dict((v, s.branch) for v, s in variants.items())

        def branch(branch: str, variant: Variant) -> Path:
            return branch + "-" + branch_part.print(variant)

        def source(branch: str, variant: Variant) -> Path:
            return Path(branch, branch_part.print(variant))

        return cls(
            variants=frozenset(variants.keys()),
            default=default,
            name=name,
            serialize=branch_part,
            branch=branch,
            source=source,
            submission_grading_title=util.print_parse.compose(
                name,
                util.print_parse.regex(submission_grading_title_holed),
            ),
        )

    @classmethod
    def from_enum_spec[X: util.enum.EnumSpec[VariantSpec]](
        cls: "type[VariantsConfig[X]]",
        enum_type: type[X],
        submission_grading_title_holed: str = default_submission_grading_title_holed,
        name_key: Callable[[str], str] = default_name_key,
    ) -> "VariantsConfig[X]":
        """
        Smart constructor with sensible defaults.
        Takes a specification enumeration.
        See from_mapping for remaining arguments.
        """
        return cls.from_mapping(
            {value: value.value for value in enum_type},
            submission_grading_title_holed=submission_grading_title_holed,
            name_key=name_key,
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class RepositoryConfig:
    """Configuration of git repositories used for the lab."""

    master: str = "main"
    """Default branch."""

    problem: str = "problem"
    """
    Branch for the given problem.
    This is a protected branch that students cannot modify.
    It is the target of the grading merge request, if configured.

    For multi-variant labs, the naming scheme for the problem branches is <problem>-<variant>.
    """

    submission: str = "submission"
    """
    Submission branch created by the lab system, if grading via merge requests is configured.
    This is a protected branch that students cannot modify.
    It is the source of the grading merge request.

    For multi-variant labs, the naming scheme for the problem branches is <submission>-<variant>.
    """

    solution: str = "solution"
    """
    Branch for the solution in the official solution project, if configured.

    For multi-variant labs, the naming scheme for the solution branches is <solution>-<variant>.
    """


@dataclasses.dataclass(frozen=True, kw_only=True)
class GradingViaMergeRequestConfig:
    """
    Configuration of new-style grading via merge requests.
    This makes it much easier for graders to reference particular lines of code.
    It also provides more fine-grained discussion threads with students.
    """

    maximum_reserve_time: datetime.timedelta = datetime.timedelta(hours=-1)
    """
    For how long does assigning a reviewer block synchronization of new submissions?
    If set to None, no limit applies.
    A negative value effectively disables this feature (this is the default).
    Warnings will be generated if a submission synchronization is blocked.

    Warning: incomplete implementation.
    See: https://github.com/ChalmersGU-data-structure-courses/lab-system/issues/57
    """


@dataclasses.dataclass(frozen=True, kw_only=True)
class LabConfig[GroupId, Outcome, Variant]:
    """Configuration of a lab in the lab system."""

    path_source: Path | None = None
    """
    Carry-over from the data structure labs layout.
    Path to the lab in the labs repository.

    Use this if you want the lab system to populate the primary and solution projects.
    Also used by current robograding/robotesting handlers.
    The lab system expects the sources in:
        <path_source>/<problem/solution>
    or for multi-variant labs:
        <path_source>/<variant>/<problem/solution>
    """

    name_semantic: str
    """
    Semantic name for the lab.
    For example, "Goose recognizer".
    """

    group_set: GroupSetConfig[GroupId] | None = None
    """
    An optional group set to use.
    If None, the lab is individual.
    """

    repository: RepositoryConfig = RepositoryConfig()
    """Configuration of git repositories used for the lab."""

    outcomes: OutcomesConfig[Outcome] = OutcomesConfig[DefaultOutcome].from_enum_spec()
    """Configuration of the possible grading outcomes of submissions."""

    variants: VariantsConfig[Variant] = VariantsConfig[StandardVariant].no_variants()
    """
    Optional configuration of lab variants.
    Use this to configure multi-language labs.
    Such labs have different problem and submission branches for each variant.
    The students can choose which variant to work with.
    """

    primary: str = "primary"
    """Slug of the primary project on Chalmers GitLab."""

    collection = "collection"
    """Slug of the collection project on Chalmers GitLab."""

    has_solution: bool = False
    """
    Whether the lab has an official solution.
    If set, a pseudo-group "solution" represents the official solution on Chalmers GitLab.
    """

    request_handlers: Mapping[str, RequestHandler]
    """
    Dictionary of request handlers.
    Its keys should be string-convertible.
    Its values are instances of the RequestHandler interface.
    The order of the dictionary determines the order in which the request matchers
    of the request handlers are tested on a student repository tag.
    """

    submission_handler_key: str = "submission"
    """
    Key of submission handler in the dictionary of request handlers.
    Its value must be an instance of SubmissionHandler.
    """

    refresh_period: datetime.timedelta | None = datetime.timedelta(minutes=60)
    """
    Lab refresh period if the script is run in an event loop.
    The webhooks on GitLab may fail to trigger in some cases:
    * too many tags pushed at the same time,
    * transient network failure,
    * hook misconfiguration.
    For that reason, we reprocess the entire lab every so often.
    The period in which this happen is sepcified by this variable.
    If it is None, no period reprocessing happens.

    Some hints on choosing suitable values:
    * Not so busy labs can have longer refresh periods.
    * A lower bound is 15 minutes, even for very busy labs.
    * It is good if the refresh periods of different labs are not
      very close to each other and do not form simple ratios.
      If they are identical, configure webhook.first_lab_refresh_delay so that
      refreshes of different labs are not scheduled for the same time.
      This would cause a lack of responsiveness for webhook-triggered updates.
    * Values of several hours are acceptable if webhook notifications work reliably.
    """

    grading_via_merge_request: GradingViaMergeRequestConfig | None = (
        GradingViaMergeRequestConfig()
    )
    """
    Configure to use new-style grading via merge requests.
    Highly recommended.
    """

    grading_sheet: grading_sheet_config.LabConfigExternal | None = (
        grading_sheet_config.LabConfigExternal()
    )
    """
    Configuration of the grading sheet for this lab.
    Required if the grading spreadsheet is enabled in the course configuration.
    """

    canvas_assignment_name: str | None = None
    """
    Optional name of a Canvas assignment used to mirror outcomes.
    The assignment should:
    * be individual (not using a group set),
    * have submissions disabled,
    * have points configured in correspondence with outcomes_config.canvas_grade.
    """

    def branch_problem(self, variant) -> str:
        return self.variants.branch(self.repository.problem, variant)

    def branch_submission(self, variant) -> str:
        return self.variants.branch(self.repository.submission, variant)

    def branch_solution(self, variant) -> str:
        return self.variants.branch(self.repository.solution, variant)


DefaultLabId = int


@dataclasses.dataclass(frozen=True, kw_only=True)
class LabIdConfig[LabId]:
    """
    Configuration of parsing and printing of references to a lab.
    Defaults only make sense for integer lab ids.
    """

    id: PrinterParser[LabId, str] = util.print_parse.int_str()
    """Human-readable id."""

    full_id: PrinterParser[LabId, str] = util.print_parse.regex_int("lab-{}")
    """
    Used:
    * as relative path on Chalmers GitLab,
    * as filename for live submissions table on Canvas.
    """

    prefix: PrinterParser[LabId, str] = util.print_parse.regex_int("lab{}-")
    """Used as prefix for projects on Chalmers GitLab."""

    name: PrinterParser[LabId, str] = util.print_parse.regex_int(
        "Lab {}",
        flags=re.IGNORECASE,
    )
    """Actual name."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class CourseConfig[LabId]:
    """
    Configuration of a course in the lab system.

    The Course class interacts with the following systems:
    * Canvas (REST client, GraphQL client?)
    * Google (Sheets)
    * Gitlab (python-gitlab, SSH multiplexer)
    * Chalmers PDB (PDB client)

    These are not yet entirely configured via this configuration.
    Instead, the Course class loads them directly.
    The authentication tokens provided in gitlab_config_personal.
    """

    time: TimeConfig = TimeConfig()

    canvas_domain: str
    """
    The Canvas domain.
    Standard values:
    * For GU courses: 'canvas.gu.se'
    * For Chalmers courses: 'chalmers.instructure.com'
    """

    canvas_course_id: int
    """
    The Canvas course identifier.
    Found in the URL when opening the Canvas course in the browser.
    """

    canvas_grading_path: PurePosixPath | None = None
    """
    Set to enable live submissions table.
    Path to (unpublished!) folder in Canvas course files.
    This is where the script will upload submission reports.
    This folder needs to exist and should not be published.
    """

    gitlab: GitlabConfig = GitlabConfig()
    """Non-course specific configuration of Chalmers GitLab."""

    gitlab_path: PurePosixPath
    """Path to the course group on Chalmers GitLab."""

    gitlab_path_graders: PurePosixPath
    """Path to the graders group on Chalmers GitLab."""

    grading_spreadsheet: grading_sheet_config.ConfigExternal | None = None
    """
    Set to enable the grading spreadsheet.
    The grading spreadsheet keeps track of grading outcomes.
    This is created by the user, but maintained by the lab script.
    """

    initials_sort_by_first_name: bool = False
    """Whether to sort initials by first name rather than last name."""

    lab_id: LabIdConfig[LabId] = LabIdConfig()
    """Configuration of formatting references to labs."""

    labs: Mapping[LabId, LabConfig]
    """The labs configured in this course."""

    initial_lab_refresh_delay: datetime.timedelta = datetime.timedelta(minutes=3)
    """
    Artificial delay between the scheduling of initial
    lab refresh events for successive labs with lab refreshes.
    The k-th lab with lab refreshed is scheduled for a refresh after:
        lab_refresh_period + k * first_lab_refresh_delay.
    Useful to avoid processing whole labs contiguously,
    causing longer response periods for webhook-triggered updates.
    """

    timeout: datetime.timedelta | None = datetime.timedelta(seconds=30)
    """Optional timeout for network operations."""

    names_informal: PrinterParser[str, str] = util.print_parse.Dict([])
    """
    Parsing and printing of informal names.
    This associates a name on Canvas with an informal names.
    It is only used for graders in the grading spreadsheet and live submissions table.

    For users not in this list, we use the first name as given on Canvas.
    This is usually fine, except if:
    * a grader wants to go by a different informal name,
    * there are two graders with the same first name.
    """

    canvas_id_to_chalmers_id_override: Mapping[int, str] = MappingProxyType({})
    """Override for the translation from Canvas user ids to Chalmers ids."""

    chalmers_id_to_gitlab_username_override: Mapping[str, str] = MappingProxyType({})
    """Override for the translation from Chalmers ids to Chalmers GitLab id."""

    machine_speed: float = 1
    """
    Relative machine speed to timing tests.
    A value of 1 corresponds to a decent 2013 desktop machine.
    """

    first_lab_refresh_delay: datetime.timedelta = datetime.timedelta(minutes=3)
    """
    Artificial delay to between the first scheduling of
    lab refresh events for successive labs with lab refreshes.
    The k-th lab with lab refreshed is scheduled for a refresh after:
        lab_refresh_period + k * first_lab_refresh_delay.
    Useful to avoid processing whole labs contiguously,
    causing longer response periods for webhook-triggered updates.
    """

    webhook_netloc_listen: util.url.NetLoc | None = None
    """
    The local net location to listen at for webhook notifications.
    Components:
    * host: if omitted, determined at runtime from routing table.
    * port: mandatory
    """

    webhook_netloc_specify: util.url.NetLoc | None = None
    """
    The net location to specify in the webhook configuration.
    Defaults to webhook_listen.
    Components default to those of webhook_listen.

    This option is useful if you are behind network address translation (NAT).
    In that case, you can:
    * specify a public network location on some server you have access to,
    * and use SSH port forwarding,
    to forward connections to webhook_netloc_listen.
    """

    @property
    def webhooks_enabled(self) -> bool:
        return self.webhook_netloc_listen is not None


@dataclasses.dataclass(frozen=True, kw_only=True)
class CourseAuth:
    """
    Authentication used by the Course class.
    If some authentication is not provided, functions depending on them cannot be used.

    SSH authentication for connecting to Chalmers GitLab uses the system configuration (".ssh" folder).
    """

    canvas_auth_token: str | None = None
    """
    Canvas authentication token.
    Used for synchronization with the Canvas course.
    """

    gitlab_private_token: str | None = None
    """
    Chalmers GitLab private token.
    Used for managing the labs.
    """

    gitlab_webhook_secret_token: str | None = None
    """
    Secret token to set and check for webhook notifications.
    The value does not matter, but must be consistent over multiple invocations that use the same webhooks.

    TODO: compute dynamically and cache?
    """

    google_credentials: Mapping[str, str] | None = None
    """
    Google credentials.
    Recommended to be for a service account.
    Used for maintaining the grading overview spreadsheet.
    """

    pdb: chalmers_pdb.Auth | None = None
    """
    Credentials for Chalmers PDB.
    Used for translating a personnummer to a CID (used for GU students).
    Format: (username, password)
    """

    @classmethod
    def from_secrets(cls, path: Path) -> "CourseAuth":
        """
        Load authentication data from secrets file.
        See template/secrets.toml for the format.
        """
        with path.open("rb") as file:
            secrets = tomllib.load(file)

        def args():
            canvas = secrets.get("canvas")
            if canvas:
                yield ("canvas_auth_token", canvas["auth_token"])

            gitlab = secrets.get("gitlab")
            if gitlab:
                yield ("gitlab_private_token", gitlab["private_token"])

                gitlab_webhook_secret_token = gitlab.get("webhook_secret_token")
                if gitlab_webhook_secret_token:
                    yield ("gitlab_webhook_secret_token", gitlab_webhook_secret_token)

            google = secrets.get("google")
            if google:
                yield ("google_credentials", google["credentials"])

            pdb = secrets.get("pdb")
            if pdb:
                yield (
                    "pdb",
                    chalmers_pdb.Auth(
                        username=pdb["username"],
                        password=pdb["password"],
                    ),
                )

        return cls(**dict(args()))

    def __repr__(self):
        """Does not leak secrets."""
        return "CourseAuth(...)"


# ## Not yet ported.

# Students taking part in labs who are not registered on Canvas.
# List of objects with the following attributes:
# * name: full name,
# * email: email address,
# * gitlab_username: username on GitLab.
# outside_canvas = []

# For translations from student provided answers files to student names on Canvas.
# Dictionary from stated name to full name on Canvas.
# Giving a value of 'None' means that the student should be ignored.
# name_corrections = {}


class LabUpdateListener[GroupId]:
    """
    A listener for lab updates.
    Currently, these are:
    * new request,
    * new response.
    """

    def groups_changed_prepare(self, ids: list[GroupId]) -> None:
        """
        Called before the collection repository is pushed.
        Use this to add tags.
        """

    def groups_changed(self, ids: list[GroupId]) -> None:
        """
        Called after the collection repository is pushed.
        Use this to update other systems.
        """
