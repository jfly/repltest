# Development

We provide a `nix` powered devshell, which you can enter with `nix develop`.

Once you're in the devshell, try running the demo:

```console
python examples/demo.py
```

# Testing

Run the tests:

```console
pytest
```

You can check code coverage by adding `--cov=repltest`. Unfortunately, 100%
test coverage is challenging to achieve reliably, as things can be pretty
sensitive to timing.

One useful trick is to run the tests repeatedly, and append to the coverage
report each time (the default is to clobber the coverage report with each test
run):

```console
rm -f .coverage && while true; do pytest --cov=repltest --cov-append; done
```

You should see this converge to 100% test coverage.
