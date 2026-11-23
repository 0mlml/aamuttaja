# Pakuralli

Lane runner in INTTI: the van drives up a forest road and rows of TNT crates come towards it; coins lie in the gaps. Path: Pelit → **Pakuralli**. Bot: `inttibot/games/pakuralli.py` (`python -m inttibot pakuralli`), played from the game's memory. Steering: hold the left or right half of the screen.

## In memory (`CarGame`, via `MiniGameManager.carGame`)
- `gameOn` (a run is going), `score`, `laneCount` (5), `laneMargin` (6: lanes at x = −12, −6, 0, 6, 12).
- `car` (`CarController`): world position (x sideways, z forward), `horizontalVel`, `horizontalAcc` (67), `horizontalMaxVel` (55), `moveInput` (−1/0/1: the steering being applied), `alive`, `halfWidth` (12.9).
- `activePoolables`: the crates (`CarGameObstacle`, three stacked per lane at the same x) and coins (`Poolable`). Rows are ~78 apart; crates jitter sideways around the lane centres (`posVariance` 0.8).

## Physics
- **Sideways movement is exactly discrete.** Every frame (60/s), `horizontalVel` moves towards input × 55 by at most 67/60 = 1.117. Letting go is input 0, the same rate down to a stop (no drift), so counter-steering brakes no faster. Velocity is always a multiple of 1.117, and x moves by multiples of 1.117/60. The input lands within ~0.05–0.08 s.
- Moving d and stopping takes 2·√(d/67): one lane (6) 0.60 s, two 0.85 s, three 1.04 s.
- Forward speed starts at ~55 units/s and grows (70–85 after a minute): rows come every ~1.1 s and less.
- **Collisions:** the van hits a crate within ~4.3 sideways (centre to centre) and from ~2 ahead of its centre to ~5 behind. The van's centre reaches ±12.6 at the road's edges.

## The bot: dynamic programming (`pakuralli_dp.py`)
- **Planner:** a grid over (x, velocity) on those quanta (1355 × 99 states) is exact. Over the next 150 frames (2.5 s) each crate blocks |x − crate x| < 4.15 while its row is between 2.5 ahead and 5 behind the van (by the forward speed). Nearer than 5.6 costs clearance; the end prefers the middle of the road. Backward induction is compiled with numba (parallel, ~50 ms) and gives the best action for every state for the next 30 frames.
- A planner thread replans continuously. The control loop decides **once per game frame**: it predicts the van's state through the decisions already sent but not yet acted on (~0.08 s of lag), and takes the plan's action for that state and frame. Deciding faster than the game's frames makes the steering chatter.
- **The forward speed** is the slope of z over the last 0.6 s (a two-sample estimate runs high).
- Best score so far: 185.
