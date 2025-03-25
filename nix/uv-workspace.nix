{ lib, inputs, ... }:

{
  perSystem =
    { prj-test-repls, pkgs, ... }:
    let
      workspace = inputs.uv2nix.lib.workspace.loadWorkspace {
        workspaceRoot = builtins.toString (
          lib.fileset.toSource {
            root = ./..;
            fileset = lib.fileset.unions [
              ../pyproject.toml
              ../uv.lock
              ../src
              # The README and examples are all tested by the Python unit tests.
              ../README.md
              ../examples
            ];
          }
        );
      };

      pyprojectOverrides = final: prev: {
        repltest = prev.repltest.overrideAttrs (old: {
          # Add tests to `passthru`.
          # From: https://pyproject-nix.github.io/uv2nix/patterns/testing.html#testing
          passthru = old.passthru // {
            tests =
              let
                # Construct a virtual environment with only the `dev` dependency-group.
                virtualenv = final.mkVirtualEnv "${final.repltest.name}-pytest-env" {
                  repltest = [ "dev" ];
                };
              in
              (old.tests or { })
              // {
                pytest = pkgs.stdenv.mkDerivation {
                  name = "${final.repltest.name}-pytest";
                  inherit (final.repltest) src;
                  nativeBuildInputs = [
                    virtualenv
                    prj-test-repls
                    pkgs.bashInteractive
                  ];

                  dontConfigure = true;

                  buildPhase = ''
                    runHook preBuild
                    pytest
                    runHook postBuild
                  '';

                  installPhase = ''
                    runHook preInstall
                    mv htmlcov $out
                    runHook postInstall
                  '';
                };
              };
          };
        });
      };

      overlay = workspace.mkPyprojectOverlay {
        sourcePreference = "wheel";
      };
      python = pkgs.python313;
      pythonSet =
        (pkgs.callPackage inputs.pyproject-nix.build.packages {
          inherit python;
        }).overrideScope
          (
            lib.composeManyExtensions [
              inputs.pyproject-build-systems.overlays.default
              overlay
              pyprojectOverrides
            ]
          );
    in
    {
      _module.args.prj = {
        inherit workspace python pythonSet;
      };
    };
}
