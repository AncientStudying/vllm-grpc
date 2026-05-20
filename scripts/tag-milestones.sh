#!/usr/bin/env bash
# Apply annotated git tags to the foundational-epoch and milestone-epoch
# merge commits on main.
#
# See the sidebar analysis (2026-05-20) for the rationale. Two slash-namespaced
# prefixes — phase/* and milestone/* — keep the historical waypoints separate
# from any future v0.x.y semver tags.
#
# Usage:
#   scripts/tag-milestones.sh [--dry-run] [--force] [--push] [--no-spike]
#
#   --dry-run   Print the git commands without executing them.
#   --force     Overwrite tags that already exist (uses `git tag -f`).
#   --push      After tagging, push the tags to `origin` (idempotent).
#   --no-spike  Skip the spike/m6.1-roadmap-additions tag.
#
# Safety:
#   - Refuses to run if HEAD is not on `main` (override with --any-branch).
#   - Skips a tag silently if it already exists, unless --force.
#   - Never auto-pushes; --push is opt-in.

set -euo pipefail

DRY_RUN=false
FORCE=false
PUSH=false
NO_SPIKE=false
ANY_BRANCH=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true ;;
        --force) FORCE=true ;;
        --push) PUSH=true ;;
        --no-spike) NO_SPIKE=true ;;
        --any-branch) ANY_BRANCH=true ;;
        -h|--help)
            sed -n '2,21p' "$0"
            exit 0
            ;;
        *)
            echo "ERROR: unknown flag: $1" >&2
            exit 1
            ;;
    esac
    shift
done

# Safety: refuse to run off main (override with --any-branch).
current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$current_branch" != "main" ]] && ! $ANY_BRANCH; then
    echo "ERROR: HEAD is on '$current_branch', not 'main'." >&2
    echo "       The tag commits are addressed by SHA, so the working-tree" >&2
    echo "       branch doesn't matter — but this guard prevents surprises." >&2
    echo "       Pass --any-branch to override." >&2
    exit 1
fi

# Tag table: TAG|COMMIT|TITLE|BODY
#
# Each row creates one annotated tag. The annotation has the title line, a
# blank line, then the body — matching git's commit-message convention.
TAGS=(
    # ---- Foundational epoch (PR #1–#15, 2026-04-28 → 2026-05-03) ----
    "phase/01-init|a022041|Phase 01 init (PR #1, 2026-04-28)|Initial repo scaffolding bootstrap."
    "phase/02-scaffolding|996be9e|Phase 02 scaffolding (PR #2, 2026-04-29)|Phase 1 project scaffolding."
    "phase/03-prompt-embeds|1641fcd|Phase 03 prompt embeds (PR #3, 2026-04-30)|Phase 2 prompt-embeds path bring-up."
    "phase/04-chat-bridge|0ae0199|Phase 04 chat bridge (PR #4, 2026-05-01)|Chat translation bridge (gRPC ↔ vLLM)."
    "phase/05-benchmark-harness|2b2c722|Phase 05 benchmark harness (PR #5, 2026-05-02)|First-pass benchmark harness."
    "phase/06-modal-frontend|046c6ce|Phase 06 Modal frontend (PR #6, 2026-05-02)|gRPC frontend deployed on Modal."
    "phase/07-modal-tunnel|190cbff|Phase 07 Modal tunnel (PR #7, 2026-05-02)|Modal-backed gRPC tunnel for the bench harness."
    "phase/08-modal-baselines|32f29ab|Phase 08 Modal real baselines (PR #9, 2026-05-02)|First real-engine baselines collected on Modal."
    "phase/09-direct-grpc-client|48642cd|Phase 09 direct gRPC client (PR #10, 2026-05-02)|Direct gRPC client path (bypasses REST proxy)."
    "phase/10-streaming-chat|c685ac8|Phase 10 streaming chat (PR #11, 2026-05-03)|Streaming chat path added to harness + frontend."
    "phase/11-phase6-complete|720a95a|Phase 11 Phase-6 complete (PR #12, 2026-05-03)|Phase 6 wire-size / prompt-embeds work consolidated."
    "phase/12-enable-prompt-embeds|42afd30|Phase 12 enable prompt embeds (PR #13, 2026-05-03)|enable_prompt_embeds path wired into the frontend."
    "phase/13-demo-polish|e6fab7a|Phase 13 demo polish (PR #14, 2026-05-03)|Demo polish, examples, and harness UX."
    "phase/14-roadmap-cut|37839c3|Phase 14 roadmap cut (PR #15, 2026-05-03)|Contributing guide + roadmap naming the M-milestones from M2 onward. End of foundational epoch."

    # ---- Measurement-milestone epoch (PR #16–#31, 2026-05-09 → 2026-05-18) ----
    "milestone/m2-ground-truth|c7eeee1|M2 — Ground-truth research (PR #16, 2026-05-09)|Ground-truth research baseline before M3 gRPC tuning."
    "milestone/m3-grpc-tuning-r1|4b13ffc|M3 — gRPC tuning round 1 (PR #17, 2026-05-10)|Initial protobuf + gRPC channel-tuning sweep."
    "milestone/m3-replan|67a99ca|M3 — time-reanalysis replan (PR #18, 2026-05-10)|M3 replan after time-axis analysis."
    "milestone/m3-phase-a-closure|0cb4bcf|M3 — Phase A closure (PR #19, 2026-05-10)|M3 Phase A complete — time-axis reanalysis published."
    "milestone/m4-time-axis|d3ec9bd|M4 — Time-axis tuning (PR #20, 2026-05-10)|M4 time-axis tuning published."
    "milestone/m5-cross-host|ac8b5be|M5 — Cross-host validation (PR #21, 2026-05-11)|M5 cross-host (CSP-edge vs plain-TCP) validation."
    "milestone/m5.1-rest-vs-grpc|8a0dddc|M5.1 — REST vs gRPC head-to-head (PR #22, 2026-05-11)|M5.1 REST-vs-gRPC head-to-head on real wire."
    "milestone/m5.2-transport-tuning|6d914c7|M5.2 — Transport tuning (PR #23, 2026-05-13)|M5.2 transport tuning — channel options + symmetric prompts."
    "milestone/m6-real-engine-mini|9922a8b|M6 — Real-engine mini-validation (PR #24, 2026-05-15)|M6 real-engine mini-validation sweep."
    "milestone/m6-analysis-update|8dbdae2|M6 — Analysis update (PR #25, 2026-05-15)|M6 analysis update with mini-validation findings."
    "milestone/m6.1-real-prompt-embeds|8eb8ebf|M6.1 — Real prompt embeds (PR #26, 2026-05-16)|M6.1 real prompt-embeds path validation."
    "milestone/m6.0a-concurrent-dispatch|5556271|M6.0a — Concurrent dispatch (PR #28, 2026-05-16)|M6.0a back-fill — concurrent dispatch for cohort sweeps."
    "milestone/m6.1.1-engine-cost-instr|7033f30|M6.1.1 — Engine-cost instrumentation (PR #27, 2026-05-17)|M6.1.1 7-bucket classifier + engine-cost instrumentation."
    "spike/m6.1-roadmap-additions|8327128|Spike — M6.1 roadmap additions (PR #29, 2026-05-17)|Scoping spike that produced the M6.1.2 + M6.1.3 plans. Not a milestone deliverable."
    "milestone/m6.1.2-methodology|2671274|M6.1.2 — Methodology discipline (PR #30, 2026-05-17)|M6.1.2 4-cohort iteration + topology-probe + cohort-set vocabulary."
    "milestone/m6.1.3-attribution|83b2b73|M6.1.3 — Attribution closure (PR #31, 2026-05-18)|M6.1.3 proxy-edge probes + audit + variance + 7-bucket attribution closure."
)

emit() {
    if $DRY_RUN; then
        # Print readably: collapse the multi-line annotation into a single
        # quoted string with a literal "\n" between title and body.
        echo "[dry-run] git tag -a${FORCE_FLAG:-} $tag $commit -m \"$title // $body\""
    else
        "$@"
    fi
}

n_created=0
n_skipped=0
n_forced=0

for row in "${TAGS[@]}"; do
    IFS='|' read -r tag commit title body <<< "$row"

    if $NO_SPIKE && [[ "$tag" == spike/* ]]; then
        echo "[skip] $tag (--no-spike)"
        continue
    fi

    # Verify the commit exists.
    if ! git rev-parse --verify --quiet "$commit^{commit}" >/dev/null; then
        echo "ERROR: $tag → $commit not found in this repo." >&2
        exit 2
    fi

    if git rev-parse --verify --quiet "refs/tags/$tag" >/dev/null; then
        if $FORCE; then
            FORCE_FLAG="f"
            emit git tag -af "$tag" "$commit" -m "$title

$body"
            unset FORCE_FLAG
            n_forced=$((n_forced + 1))
        else
            echo "[skip] $tag already exists (pass --force to overwrite)"
            n_skipped=$((n_skipped + 1))
        fi
    else
        emit git tag -a "$tag" "$commit" -m "$title

$body"
        n_created=$((n_created + 1))
    fi
done

echo
echo "Summary: created=$n_created  forced=$n_forced  skipped=$n_skipped"

if $PUSH; then
    echo
    echo "Pushing tags to origin..."
    emit git push origin --tags
fi

if $DRY_RUN; then
    echo
    echo "Dry run complete. Re-run without --dry-run to apply."
fi
