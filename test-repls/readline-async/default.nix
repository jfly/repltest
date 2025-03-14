{ readline, runCommandCC }:

let
  pname = "test-repl-readline-async";
in
runCommandCC pname
  {
    buildInputs = [ readline ];
  }
  ''
    bin=$out/bin/${pname}
    mkdir -p "$(dirname "$bin")"
    $CC -lreadline ${./main.c} -o "$bin"
  ''
