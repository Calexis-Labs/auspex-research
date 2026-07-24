"""Topoloji uretici: TopoSpec'ten clab YAML + node basina TAM startup-config.

Cikti dizini lab adina gore ayrilir:
  lab/build/<name>/<name>.clab.yml + lab/build/<name>/configs/<node>.cfg

build() saf dosya uretimidir — aga dokunmaz; testler tmp dizine yazabilir.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from lab import topo
from lab.topo import TopoSpec

BUILD_DIR = Path(__file__).parent / "build"
CEOS_IMAGE_DEFAULT = "ceos:lab"
HOST_IMAGE_DEFAULT = "ghcr.io/srl-labs/network-multitool"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def clab_file(spec: TopoSpec, out_dir: Path | None = None) -> Path:
    """Uretilen clab.yml'nin yolu (build cagrilmadan da hesaplanabilir)."""
    root = out_dir if out_dir is not None else BUILD_DIR / spec.name
    return root / f"{spec.name}.clab.yml"


def build(
    spec: TopoSpec | None = None,
    ceos_image: str = CEOS_IMAGE_DEFAULT,
    out_dir: Path | None = None,
) -> Path:
    """Topoloji dosyalarini uretir, clab.yml yolunu dondurur."""
    spec = spec or topo.default_spec()
    env = _env()

    clab_yml = clab_file(spec, out_dir)
    configs = clab_yml.parent / "configs"
    configs.mkdir(parents=True, exist_ok=True)

    cfg_tpl = env.get_template("ceos.cfg.j2")
    for name, node in spec.ceos_nodes.items():
        (configs / f"{name}.cfg").write_text(
            cfg_tpl.render(name=name, node=node, l3=spec.l3, features=spec.features)
        )

    topo_tpl = env.get_template("topology.clab.j2")
    clab_yml.write_text(
        topo_tpl.render(spec=spec, ceos_image=ceos_image, host_image=HOST_IMAGE_DEFAULT)
    )
    return clab_yml


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="TopoSpec'ten lab dosyalari uret")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--name", default=topo.LAB_NAME)
    ap.add_argument("--image", default=CEOS_IMAGE_DEFAULT)
    args = ap.parse_args()

    spec = topo.build_spec(args.seed, name=args.name)
    path = build(spec, ceos_image=args.image)
    print(f"uretildi: {path}")
    for cfg in sorted((path.parent / "configs").glob("[!.]*.cfg")):
        print(f"uretildi: {cfg}")
