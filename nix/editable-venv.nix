{ inputs, lib, ... }:
{
  imports = [ inputs.devshell.flakeModule ];
  perSystem =
    { prj, pkgs, ... }:
    {
      devshells.default =
        let
          # Create an overlay enabling editable mode for all local dependencies.
          editableOverlay = prj.workspace.mkEditablePyprojectOverlay {
            root = "$PRJ_ROOT";
          };

          # Override previous set with our overrideable overlay.
          editablePythonSet = prj.pythonSet.overrideScope (
            lib.composeManyExtensions [
              editableOverlay
            ]
          );

          # Build virtual environment, with local packages being editable.
          #
          # Enable all optional dependencies for development.
          virtualenv = editablePythonSet.mkVirtualEnv "dev-env" prj.workspace.deps.all;
        in
        {
          packages = [
            virtualenv
            pkgs.uv
          ];

          env = lib.attrsToList {
            # Don't create venv using uv.
            UV_NO_SYNC = "1";

            # Force uv to use Python interpreter from venv.
            UV_PYTHON = "${virtualenv}/bin/python";

            # Prevent uv from downloading managed Python's.
            UV_PYTHON_DOWNLOADS = "never";
          };
        };
    };
}
