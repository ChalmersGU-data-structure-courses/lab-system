$2 == "SCRIPTS" {
    print "<script type=\"text/javascript\">"
    while ("cat js/trees.js" | getline) print
    while ("cat generated/obfuscated.js" | getline) print
    print "</script>"
    next
}

/^ *<script/ {
    next
}

{ print }
