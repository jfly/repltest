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
              # The README and examples are all tested by the Python unit tests.
              ../README.md
              ../examples
            ];
          }
        );
      };

      pyprojectOverrides = final: prev: {
        # Patch pytest-cov with a workaround for
        # https://github.com/pytest-dev/pytest-cov/issues/465, which affects
        # coverage reporting during our tests.
        pytest-cov = (prev.pytest-cov.override { sourcePreference = "sdist"; }).overrideAttrs (old: {
          patches = (old.patches or [ ]) ++ [
            (pkgs.fetchpatch {
              name = "Ensure source dirs are absolute";
              url = "https://patch-diff.githubusercontent.com/raw/pytest-dev/pytest-cov/pull/681.patch";
              hash = "sha256-1OvUhQM1a/tGYopMDnTEt8/jhhuAAZPBJOCy4/88A88=";
            })
          ];
          nativeBuildInputs = old.nativeBuildInputs ++ [
            (final.resolveBuildSystem {
              setuptools = [ ];
            })
          ];
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

      # Create an overlay enabling editable mode for all local dependencies.
      editableOverlay = workspace.mkEditablePyprojectOverlay {
        root = "$PRJ_ROOT";
      };

      # Override previous set with our overrideable overlay.
      editablePythonSet = pythonSet.overrideScope (
        lib.composeManyExtensions [
          editableOverlay
        ]
      );
    in
    {
      _module.args.prj = {
        inherit
          workspace
          python
          pythonSet
          editablePythonSet
          ;
      };
    };
}
