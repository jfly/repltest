{ inputs, ... }:

{
  perSystem =
    {
      self',
      pkgs,
      prj,
      ...
    }:
    let
      repltest = prj.pythonSet.repltest;

      inherit (pkgs.callPackages inputs.pyproject-nix.build.util { }) mkApplication;
    in
    {
      checks = {
        inherit (repltest.passthru.tests) pytest;
      };

      packages.default = self'.packages.repltest;
      packages.repltest = mkApplication {
        venv = prj.pythonSet.mkVirtualEnv "application-env" prj.workspace.deps.default;
        package = repltest;
      };
    };
}
