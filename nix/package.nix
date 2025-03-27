{ inputs, ... }:

{
  perSystem =
    {
      self',
      pkgs,
      prj,
      prj-test-repls,
      ...
    }:
    let
      repltest = prj.pythonSet.repltest;

      inherit (pkgs.callPackages inputs.pyproject-nix.build.util { }) mkApplication;
    in
    {
      checks = {
        repltest =
          # Modified from: https://pyproject-nix.github.io/uv2nix/patterns/testing.html#testing
          # We use an editable venv for tests because it makes coverage
          # reporting easier. Without this, you are able to import repltest in
          # 2 different ways:
          #
          #   1. Relatively through the `src` directory.
          #   2. In the `site-packages` directory of your python env (this
          #      happens during our "end to end" tests when we run `repltest`
          #      as a subprocess).
          #
          # It's possible to teach `coverage.py` that multiple paths are
          # actually the same thing [0], but I don't like having multiple
          # copies of the same thing (even if they're identical). An editable
          # venv fixes this issue, so let's use one!
          #
          # [0]: https://coverage.readthedocs.io/en/latest/config.html#config-paths
          let
            # Construct a virtual environment with only the `dev` dependency-group.
            editableVenv = prj.editablePythonSet.mkVirtualEnv "test-env" {
              repltest = [ "dev" ];
            };
          in
          pkgs.stdenv.mkDerivation {
            name = "${prj.editablePythonSet.repltest.name}-pytest";
            inherit (prj.editablePythonSet.repltest) src;
            nativeBuildInputs = [
              editableVenv
              prj-test-repls
              pkgs.bashInteractive
            ];

            dontConfigure = true;

            buildPhase = ''
              export PRJ_ROOT=$PWD

              runHook preBuild
              pytest --cov-report term --cov-report html
              runHook postBuild
            '';

            # Install the HTML coverage report into the build output.
            installPhase = ''
              runHook preInstall
              mv htmlcov $out
              runHook postInstall
            '';
          };
      };

      packages.default = self'.packages.repltest;
      packages.repltest = mkApplication {
        venv = prj.pythonSet.mkVirtualEnv "application-env" prj.workspace.deps.default;
        package = repltest;
      };
    };
}
