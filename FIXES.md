Now I'll start fixing. Priority order from the audit, implementing now:

**P0 (Blocks):**
1. Exit-offer handler — detect wellness topic keywords before defaulting to chat/exit
2. Repetition safeguard — throw CRITICAL and force state break instead of silent warn
3. Avoidance counter — sub-category selections should never be classified as deflecting

**P1 (Degrades quality):**
4. Low-confidence facts (<60) filtered before user-facing presentation
5. Default else-case logs loudly instead of silent fallback
6. Greeting forced transition after turn 3
7. Fuzzy matching on option parsing

Applying now...