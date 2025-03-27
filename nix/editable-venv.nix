{ inputs, lib, ... }:
{
  imports = [ inputs.devshell.flakeModule ];
  perSystem =
    { prj, pkgs, ... }:
    {
      devshells.default =
        let
          # Build virtual environment, with local packages being editable.
          #
          # Enable all optional dependencies for development.
          editableVenv = prj.editablePythonSet.mkVirtualEnv "dev-env" prj.workspace.deps.all;
        in
        {
          packages = [
            editableVenv
            pkgs.uv
          ];

          env = lib.attrsToList {
            # Don't create venv using uv.
            UV_NO_SYNC = "1";

            # Force uv to use Python interpreter from venv.
            UV_PYTHON = "${editableVenv}/bin/python";

            # Prevent uv from downloading managed Pythons.
            UV_PYTHON_DOWNLOADS = "never";
          };
        };
    };
}
