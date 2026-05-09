from __future__ import annotations

from .common import TRANSLATE, is_probably_untranslated
from .latex_ops import fix_translation, sanitize_latex_source, split_nodes


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_itemsep_not_split() -> None:
    source = r"\newenvironment{tight_itemize}{\begin{itemize} \itemsep" + "\n-2.1pt}{\\end{itemize}}\n"
    normalized = sanitize_latex_source(source)
    assert_true(r"\itemsep" in normalized, "sanitize_latex_source must preserve \\itemsep")
    assert_true(r"\item sep" not in normalized, "sanitize_latex_source must not split \\itemsep")


def test_inline_references_stay_with_translation_segment() -> None:
    source = "An overview of the method is shown in~\\autoref{fig:feature-extraction}."
    segments = [node.text for node in split_nodes(source) if node.kind == TRANSLATE]
    assert_true(
        any(r"\autoref{fig:feature-extraction}" in segment for segment in segments),
        "inline references should stay attached to the translated sentence",
    )


def test_reference_inventory_repair() -> None:
    original = "An overview is shown in~\\autoref{fig:feature-extraction}."
    translated = r"概览如~\Cref{...}所示。\autoref{fig:feature-extraction}"
    fixed = fix_translation(translated, original)
    assert_true(r"\Cref{...}" not in fixed, "placeholder references must be removed")
    assert_true(
        fixed.count(r"\autoref{fig:feature-extraction}") == 1,
        "reference inventory repair should keep exactly one original reference",
    )

    original = r"tool habits~\cite{viegas2007manyeyes,battle2018beagle}"
    translated = r"工具习惯~\cite{}\cite{viegas2007manyeyes,battle2018beagle}"
    fixed = fix_translation(translated, original)
    assert_true(r"\cite{}" not in fixed, "empty citations must be removed")
    assert_true(
        fixed.count(r"\cite{viegas2007manyeyes,battle2018beagle}") == 1,
        "duplicate citation repair should keep exactly one original citation",
    )

    original = "This sentence has no reference."
    translated = r"这个句子没有引用~\cite{invented2026}"
    fixed = fix_translation(translated, original)
    assert_true(r"\cite{invented2026}" not in fixed, "invented non-empty citations must be removed")

    original = r"Proof of identity \eqref{Yao-(3.1)-orth-simply}."
    translated = r"\eqref{\noindent \bf Proof of identity \eqref{Yao-(3.1)-orth-simply}.}"
    fixed = fix_translation(translated, original)
    assert_true(
        fixed == r"\eqref{Yao-(3.1)-orth-simply}",
        "nested/prose-corrupted reference keys must be restored from the original inventory",
    )


def test_frontmatter_title_can_be_segmented() -> None:
    source = (
        "\\documentclass{article}\n"
        "\\newcommand{\\papertitle}{Toward a Scalable Census of Dashboard Designs in the Wild}\n"
        "\\begin{document}\n"
        "\\title{\\papertitle}\n"
        "\\maketitle\n"
        "\\end{document}\n"
    )
    segments = [node.text for node in split_nodes(source) if node.kind == TRANSLATE]
    assert_true(
        any("Toward a Scalable Census" in segment for segment in segments),
        "title macro content should be translatable instead of fully protected",
    )


def test_identity_frontmatter_is_not_untranslated_warning() -> None:
    original = (
        r"\author{Michael Correll} \affiliation{ \institution{Tableau Research} "
        r"\city{Washington} \country{USA}} \email{mcorrell@tableau.com}"
    )
    translated = (
        r"\author{Michael Correll} \affiliation{ \institution{Tableau Research} "
        r"\city{华盛顿} \country{美国}} \email{mcorrell@tableau.com}"
    )
    assert_true(
        not is_probably_untranslated(original, translated),
        "author/email frontmatter should not be flagged as an untranslated prose segment",
    )


def test_control_word_cjk_and_missing_item_repair() -> None:
    source = r"\newcommand{\method}{UniPool}" + "\n" + r"\method中表现稳定。"
    normalized = sanitize_latex_source(source)
    assert_true(r"\method{}中" in normalized, "control words before CJK text need an explicit boundary")

    source = "\\begin{itemize}\n对于紧支撑的先验，我们证明结果。\n\\end{itemize}\n"
    normalized = sanitize_latex_source(source)
    assert_true(r"\item 对于紧支撑的先验" in normalized, "itemize prose must be restored as an item")


def test_econ_compile_normalizers() -> None:
    source = (
        "\\documentclass{article}\n"
        "{\\catcode/=0 \\catcode\\\\=12/gdef/mkillslash\\#1{#1}}\n"
        "\\edef\\jobnametmp{\\expandafter\\string\\csname embayes2_apx\\endcsname}\n"
        "\\edef\\jobnameapx{\\expandafter\\mkillslash\\jobnametmp}\n"
        "\\begin{document}\n\\end{document}\n"
    )
    normalized = sanitize_latex_source(source)
    assert_true(r"\edef\jobnameapx{embayes2" in normalized, "slash catcode jobname probe should be normalized")
    assert_true(r"\jobnametmp" not in normalized, "temporary slash-removal jobname helper should be removed")
    assert_true(r"\mkillslash" not in normalized, "unstable slash catcode helper should be removed")

    normalized = sanitize_latex_source(r"关于\（G\）、\（H\）的定义")
    assert_true(r"\（" not in normalized and r"\）" not in normalized, "escaped CJK punctuation should be unescaped")


def main() -> int:
    tests = [
        test_itemsep_not_split,
        test_inline_references_stay_with_translation_segment,
        test_reference_inventory_repair,
        test_frontmatter_title_can_be_segmented,
        test_identity_frontmatter_is_not_untranslated_warning,
        test_control_word_cjk_and_missing_item_repair,
        test_econ_compile_normalizers,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"regression checks passed: {len(tests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
