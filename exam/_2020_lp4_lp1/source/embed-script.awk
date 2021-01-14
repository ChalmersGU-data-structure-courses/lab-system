{
    if (match($0, /^ *<script type="text\/javascript" src="(.*)"><\/script> *$/, m)) {
        print "<script type=\"text/javascript\">"
        while ("cat generated/" m[1] | getline) print
        print "</script>"
    } else print
}
