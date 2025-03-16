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
                    prj-test-repls
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

        seccomp = prev.seccomp.overrideAttrs (
          old:
          let
            pySeccomp = python.pkgs.seccomp.override {
              libseccomp = pkgs.libseccomp.overrideAttrs (oldAttrs: {
                # TODO: upstream this to libseccomp.
                patches = (oldAttrs.patches or [ ]) ++ [ ./seccomp-add-set_notify_fd.patch ];
              });
            };
          in
          {
            buildInputs = (old.buildInputs or [ ]) ++ pySeccomp.buildInputs;
            src = pySeccomp.dist;
          }
        );
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

      # Here we do some hackiness so `uv` can find the `seccomp` Python library,
      # which is not distributed on `pypi.org`. It is available in `nixpkgs`,
      # though. For more information:
      #  - https://github.com/seccomp/libseccomp/issues/461
      #  - https://github.com/pyproject-nix/pyproject.nix/issues/267
      devshells.default.devshell.startup.uv-find-links.text =
        let
          uvFindLinks = pkgs.symlinkJoin {
            name = "uv-links";
            paths = [
              python.pkgs.seccomp.dist
            ];
          };
        in
        # bash
        ''
          export UV_FIND_LINKS=$PWD/.uv-find-links
          ln -sfT ${uvFindLinks} "$UV_FIND_LINKS"
        '';
    };
}
