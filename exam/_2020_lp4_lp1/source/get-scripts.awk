{
    if (match($0, /^ *<script type="text\/javascript" src="(.*)"><\/script> *$/, m)) {
        print "generated/" m[1]
    }
}
