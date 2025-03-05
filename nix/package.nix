{
  perSystem =
    { prj, ... }:
    let
      repl-driver = prj.pythonSet.repl-driver;
    in
    {
      checks = {
        inherit (repl-driver.passthru.tests) pytest;
      };

      packages.wheel = repl-driver.override {
        pyprojectHook = prj.pythonSet.pyprojectDistHook;
      };

      packages.sdist =
        (repl-driver.override {
          pyprojectHook = prj.pythonSet.pyprojectDistHook;
        }).overrideAttrs
          (old: {
            env.uvBuildType = "sdist";
          });
    };
}
