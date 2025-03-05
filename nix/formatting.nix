{ inputs, ... }:
{
  imports = [ inputs.treefmt-nix.flakeModule ];

  perSystem.treefmt = {
    projectRootFile = "flake.nix";
    programs = {
      nixfmt.enable = true;
      clang-format.enable = true;
      ruff-check.enable = true;
      ruff-format.enable = true;
    };
  };
}
