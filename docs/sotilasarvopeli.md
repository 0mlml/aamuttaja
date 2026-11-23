# Sotilasarvopeli

Quiz minigame in INTTI. Path: home → menu → **Pelit** → **Sotilasarvopeli**. Bot: `inttibot/games/sotilas.py` (`python -m inttibot sotilas <maa|meri|koulutus|aakkoset>`): every answer is read from the game's memory. Positions in px at 540×1200.

## The game
- **Menu:** four category tiles: *Maa- ja ilmavoimat* (ranks), *Merivoimat* (navy ranks), *Koulutushaarat* (service-branch emblems), *Aakkoset* (alphabet). Buttons: **Pelaa**, **Opettele** (the learn list), **Poistu**.
- **A question:** a picture, the score, a timer bar, and 2 answer buttons at first, 3 from score 2, 4 later. **A wrong answer or a timeout ends the round**, and the timer gets faster as the score rises.
- **Aakkoset:** a letter, and the answer is typed and submitted with Enter. It's the **NATO alphabet in the game's spelling**: Alfa, Bravo, Charlie, Delta, Echo, Foxtrot, Golf, Hotel, India, **Juliett**, Kilo, Lima, Mike, November, Oscar, Papa, Quebec, Romeo, Sierra, Tango, Uniform, Victor, **Whiskey**, **Xray**, Yankee, Zulu.

## In memory
- `QuizGame` (via `MiniGameManager.quizGame`; its `INSTANCE` is null until the quiz has been opened): `selectedGameMode` (0 maa, 1 meri, 2 koulutus, 3 aakkoset), `score`, `clickable`, `choiceButtons`, `abcInputFieldValue` (Aakkoset: the field's text), the answer data per category (`rankDataArmy`, `rankDataNavy`, `branchesData`: `QuizDataBlock` with `rankNames` etc., filled when the quiz opens).
- **The round is a coroutine object** (a C# iterator), `<GameCoroutine>d__105`; for Aakkoset `<GameCoroutineABC>d__106`. Its fields are the method's locals: `<choices>5__5` (the answer strings, an array), `<correctChoiceIndex>5__6`, `<correctChoice>5__7`; Aakkoset: `<correctChoice>5__3` (the NATO word). `<>4__this` is the quiz; `<>1__state` is −1 once the round is over (`roundActive` drops between questions, so it can't tell). The object is found by scanning memory for its class pointer at the start of a round (near the last one first).
- **The buttons**: `QuizChoiceButton` has `index` (into the choices) and a world position; screen y = 733.5 − 135 × world y.

## The bot
Start a round (mode tile, Pelaa) and find its coroutine. For each question (a new `<correctChoice>` object, and `clickable`): tap the button whose `index` is the correct one, or for Aakkoset tap the field, type the word with the injector, check that `abcInputFieldValue` holds it, and press Enter; then wait for `score` to count it. The round's end is checked three times 0.2 s apart (a single read can catch the coroutine mid-step).

The bot never misses, so a round only ends when it stops answering: `--until N` stops at N and the timer ends the round, which saves the score. A keyboard left up after Aakkoset covers Pelaa: Android's input method service says whether it's shown (`dumpsys input_method`, `mInputShown`), and its OK (483, 700) closes it. Never the back key: on the wrong screen it leaves INTTI.
