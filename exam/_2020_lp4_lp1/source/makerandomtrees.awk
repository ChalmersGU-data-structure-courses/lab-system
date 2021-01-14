BEGIN {
    getline seed
    srand(seed)
    for (i = 0; i < 100; i++) rand()
}

{
    while (i = index($0, "X")) {
        n = int(10 * rand())
        $0 = substr($0, 1, i-1) n substr($0, i+1)
    }

    print $0
}
