"""CLI 入口：paper-extract <pdf> --out <dir> [flags]

安装后由 pyproject [project.scripts] 注册为 `paper-extract` 命令。
"""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog='paper-extract',
        description='Extract figures / tables / captions / formulas from a literature PDF',
    )
    ap.add_argument('pdf', help='input PDF path')
    ap.add_argument('--out', required=True, help='output directory')
    ap.add_argument(
        '--no-formulas', action='store_true',
        help='skip formula detection/recognition',
    )
    ap.add_argument(
        '--no-ocr', action='store_true',
        help='skip caption OCR (PaddleOCR)',
    )
    ap.add_argument(
        '--layout-only', action='store_true',
        help='only layout detection (figures/tables bbox + crops), no OCR, no formulas',
    )
    ap.add_argument(
        '--no-figures', action='store_true',
        help='skip figure cropping (only tables + captions)',
    )
    ap.add_argument(
        '--no-tables', action='store_true',
        help='skip table cropping (only figures + captions)',
    )
    ap.add_argument('--dpi', type=int, default=200, help='PDF render DPI (default 200)')
    ap.add_argument(
        '--conf', type=float, default=0.25,
        help='detection confidence threshold (default 0.25)',
    )
    args = ap.parse_args(argv)

    if args.layout_only:
        kwargs = dict(layout=True, ocr=False, formulas=False)
    else:
        kwargs = dict(
            layout=True,
            ocr=not args.no_ocr,
            formulas=not args.no_formulas,
        )

    crop_classes = None
    if args.no_figures or args.no_tables:
        from .layout import CROP_CLASSES
        crop_classes = set(CROP_CLASSES)
        if args.no_figures:
            crop_classes.discard('figure')
        if args.no_tables:
            crop_classes.discard('table')
        kwargs['crop_classes'] = crop_classes

    from .pipeline import extract

    out = extract(
        args.pdf,
        args.out,
        dpi=args.dpi,
        conf=args.conf,
        **kwargs,
    )

    print(f'✓ Extracted to {out["summary_path"].parent}')
    return 0


if __name__ == '__main__':
    sys.exit(main())