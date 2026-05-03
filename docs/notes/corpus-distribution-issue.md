# Corpus Distribution Issue: seq_lens Cluster at Bucket Ceilings

## Observed Behavior

`scripts/python/gen_embed_corpus.py` produces 20 embedding corpus entries across four
seq-len buckets, but the actual sequence lengths cluster at each bucket's ceiling rather
than being spread within the range:

| bucket | range    | actual seq_lens in corpus           |
|--------|----------|-------------------------------------|
| short  | 1–16     | 9, 16, 16, 16, 16                   |
| medium | 17–48    | 35, 41, 48, 48, 48                  |
| long   | 49–128   | 128, 128, 128, 128, 128             |
| full   | 129–256  | 256, 256, 256, 256, 256             |

The root cause is that the script concatenates source prompts in order until the bucket
ceiling is reached, then truncates to exactly the ceiling.  Any source prompt shorter
than the ceiling becomes the single representative for that bucket.  Longer buckets
("long", "full") fill immediately to the ceiling, so all five entries land at the same
length.

## Impact

- The wire-size comparison averages across all 20 entries.  Because the long and full
  buckets dominate total byte counts, the mean is driven almost entirely by the largest
  tensors — short and medium sequences are underrepresented.
- The benchmark overstates the overhead advantage of gRPC-direct for realistic workloads
  where short sequences are common.
- seq_len diversity within a bucket is important for measuring how encoding overhead
  scales (the base64 +33% is multiplicative, so the mean overhead in absolute bytes is
  skewed by the longest tensors).

## Suggested Fix

Replace the ceiling-fill approach with a targeted distribution strategy:

1. For each bucket, pick a spread of seq_lens at e.g. 25%, 50%, 75%, and 100% of the
   range (ceiling).  For a 5-entry bucket, use 20%, 40%, 60%, 80%, 100%.
2. For each target length, generate a fresh random embedding from `model.embed_tokens`
   with exactly that many tokens (use a real prompt tokenized to the right length, or
   pad/trim a fixed vocab sample).
3. This ensures the short bucket has entries at roughly 3, 6, 10, 13, 16 and the medium
   bucket at roughly 25, 32, 38, 44, 48.

Alternatively, randomize within each bucket by sampling seq_len uniformly from
`[ceil_prev + 1, ceil_current]` for each of the five entries, using a fixed seed for
reproducibility.

## Status

Noted 2026-05-03.  No fix applied; corpus files are checked in as-is.  Regenerating
the corpus requires the `investigation` dependency group (PyTorch + Transformers) and
the Modal GPU environment for weight access, so a fix should be bundled with the next
corpus regeneration cycle.
