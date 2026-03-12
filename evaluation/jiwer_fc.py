from jiwer import process_words

reference = "the cat sat on the mat"
hypothesis = "the cat sat on a mat"

result = process_words(reference, hypothesis)

print(f"WER: {result.wer:.1%}")        # 16.7%
print(f"Substitutions: {result.substitutions}")  # 1  ("the" → "a")
print(f"Insertions: {result.insertions}")        # 0
print(f"Deletions: {result.deletions}")          # 0
print(f"Hits: {result.hits}")                    # 5  (correct words)
