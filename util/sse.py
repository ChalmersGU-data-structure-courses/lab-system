import io


class ServerSideEvents:
    def __init__(self, out: io.IOBase):
        self.out = out
        self.flushing = True

    def flush(self):
        if self.flushing:
            self.out.flush()

    def validate_fragment(self, fragment: bytes):
        assert all(not (char in fragment) for char in [b"\n", b"\r"])

    def write_line(self, *parts: bytes):
        for part in parts:
            self.validate_fragment(part)
        self.out.write(b"".join([*parts, b"\n"]))

    def write_blank(self):
        self.write_line()

    def write_comment(self, comment: bytes):
        self.write_line(b":", comment)

    def write_field(self, key: bytes, value: bytes):
        self.write_line(key, b": ", value)

    def write_data(self, line: bytes):
        self.write_field(b"data", line)

    def write_heartbeat(self):
        self.write_comment(b"heartbeat")
        self.flush()

    def write_message(self, event: bytes | None, data: bytes | None):
        if event is not None:
            self.write_field(b"event", event)
        if data is not None:
            for line in data.splitlines():
                self.write_field(b"data", line)
        self.write_blank()
        self.flush()
