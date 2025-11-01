## Objective
- Produce a professional synthesis of the repository's OPI (On-Chain Process Interface) design with a focus on the `floodfish` Poisson OPI implementation.
- Simulate available execution paths/tests to observe `floodfish` behaviour and iterate as far as practical within the environment.

## Key Steps
1. Gather architectural and operational context (docs, registry, base classes) to verify OPI coherence.
2. Deep-dive into `src/opi/operations/poisson_opi` with emphasis on `processor.py` for the `floodfish` ticker; map data flow and dependencies.
3. Identify runnable simulations (unit/functional/integration tests or scripts) that exercise Poisson OPIs and specifically `floodfish`; prepare environment requirements.
4. Execute the maximum feasible set of simulations locally (parallel where safe), capturing logs and outcomes for analysis.
5. Synthesize findings: architecture coherence, proposed behaviour, simulation results, gaps, and recommendations.

## Deliverables
- Professional narrative covering architecture, `floodfish` logic, and simulated run outcomes with iterations noted.
- Notes on limitations and next steps if further validation is required.
