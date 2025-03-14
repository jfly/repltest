{ runCommandCC }:

let
  pname = "test-repl-read-cooked";
in
runCommandCC pname { } ''
  bin=$out/bin/${pname}
  mkdir -p "$(dirname "$bin")"
  $CC ${./main.c} -o "$bin"
''
