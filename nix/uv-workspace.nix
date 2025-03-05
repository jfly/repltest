{ lib, inputs, ... }:

{
  perSystem =
    { pkgs, ... }:
    let
      workspace = inputs.uv2nix.lib.workspace.loadWorkspace {
        workspaceRoot = builtins.toString (
          lib.fileset.toSource {
            root = ./..;
            fileset = lib.fileset.unions [
              ../pyproject.toml
              ../uv.lock
              ../src
            ];
          }
        );
      };

      pyprojectOverrides = final: prev: {
        repl-driver = prev.repl-driver.overrideAttrs (old: {
          # Add tests to `passthru`.
          # From: https://pyproject-nix.github.io/uv2nix/patterns/testing.html#testing
          passthru = old.passthru // {
            tests =
              let
                # Construct a virtual environment with only the `dev` dependency-group.
                virtualenv = final.mkVirtualEnv "repl-driver-pytest-env" {
                  repl-driver = [ "dev" ];
                };

              in
              (old.tests or { })
              // {
                pytest = pkgs.stdenv.mkDerivation {
                  name = "${final.repl-driver.name}-pytest";
                  inherit (final.repl-driver) src;
                  nativeBuildInputs = [
                    virtualenv
                  ];
                  dontConfigure = true;

                  buildPhase = ''
                    runHook preBuild
                    pytest --cov tests --cov-report html src
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

        python-ptrace =
          (prev.python-ptrace.override {
            sourcePreference = "sdist";
          }).overrideAttrs
            (old: {
              nativeBuildInputs = old.nativeBuildInputs ++ [
                (final.resolveBuildSystem {
                  setuptools = [ ];
                })
              ];
              patches = (old.patches or [ ]) ++ [
                # https://github.com/vstinner/python-ptrace/pull/90
                (pkgs.fetchpatch {
                  url = "https://github.com/vstinner/python-ptrace/pull/90/commits/5dac4505fa7500dba38d365503cee487a0b0a11a.patch";
                  hash = "sha256-+LGcts6GeYcAjSaqtToGMhqj+ZbsjdaxPTXGMbEBPIc=";
                })
              ];
            });
      };
      overlay = workspace.mkPyprojectOverlay {
        sourcePreference = "wheel";
      };
      python = pkgs.python3;
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
