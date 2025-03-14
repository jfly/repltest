{ lib, inputs, ... }:

{
  perSystem =
    { prj-fixtures, pkgs, ... }:
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

      hacks = pkgs.callPackage inputs.pyproject-nix.build.hacks { };

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
                  ] ++ prj-fixtures;

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

        # Here we do some hackiness to pull in the `seccomp` Python library,
        # which is not distributed on `pypi.org`. It is available in `nixpkgs`,
        # though. For more information:
        #  - https://github.com/seccomp/libseccomp/issues/461
        #  - https://github.com/pyproject-nix/pyproject.nix/issues/267
        seccomp = hacks.nixpkgsPrebuilt {
          from = python.pkgs.seccomp.override {
            libseccomp = pkgs.libseccomp.overrideAttrs (oldAttrs: {
              # TODO: upstream this to libseccomp.
              patches = (oldAttrs.patches or [ ]) ++ [ ./seccomp-add-set_notify_fd.patch ];
            });
          };
        };
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
