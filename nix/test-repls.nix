{
  perSystem =
    { lib, pkgs, ... }:
    let
      testReplPkgs = lib.pipe ../test-repls [
        builtins.readDir
        (lib.filterAttrs (_name: type: type == "directory"))
        (lib.mapAttrs' (
          name: type:
          let
            package = pkgs.callPackage (../test-repls + "/${name}") { };
          in
          lib.nameValuePair name package
        ))
      ];

      test-repls = pkgs.symlinkJoin {
        name = "test-repls";
        paths = lib.attrValues testReplPkgs;
        passthru.pkgs = testReplPkgs;
      };
    in
    {
      devshells.default.packages = [ test-repls ];
      _module.args.prj-test-repls = test-repls;
    };
}
