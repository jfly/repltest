{ inputs, lib, ... }:
{
  imports = [
    ./uv2nix.nix
    inputs.devshell.flakeModule
  ];

  perSystem =
    { pkgs, ... }:
    {
      uv2nix = {
        python = pkgs.python313;

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

        nativeCheckInputs = [ pkgs.bashInteractive ];
      };
    };
}
