BEGIN {}

{
    if (i = index($0, "X")) {
        n++
        getline data < ("data" n)
        $0 = substr($0, 1, i-1) data substr($0, i+1)
    }

    print $0
}
