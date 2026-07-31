# AI Mockup Engine

Last Updated: 2026-07-31

===============================================================================
CURRENT TASK (READ THIS FIRST)
===============================================================================

Current milestone:

Build the first production-quality Bella Canvas 3001 asset.

Everything else is secondary.

Current state:

- Core engine is complete.
- Pipeline is operational.
- Calibration asset is complete.
- Current work focuses ONLY on finishing the first real production asset.

Do NOT start new features.

Do NOT redesign architecture.

Do NOT optimize existing code unless explicitly requested.

Only work on the task requested by the user.

===============================================================================
# IMPORTANT

This file is the single source of truth for this project.

Assume everything written here is already verified.

Do not re-check completed work unless explicitly requested or a failing test requires it.

Repository-wide scans are discouraged and should only happen when absolutely necessary.


===============================================================================

WORKING RULES

Before doing anything:

1. Read this file completely.

2. Assume everything listed as COMPLETE is correct.

3. Do NOT scan the repository unless it is absolutely required for the requested task.

4. Do NOT inspect old commits.

5. Do NOT generate architecture proposals unless requested.

6. Do NOT produce project status reports unless requested.

7. Do NOT re-verify completed modules.

8. Do NOT search for bugs without a failing test.

9. Work only on the user's current task.

10. When finished, STOP.

Every response should follow this format:

1. What was changed
2. Which files changed
3. How it was tested
4. Final result

Then wait for the next task.

===============================================================================
PROJECT GOAL
===============================================================================

The goal is to build a production-quality AI mockup engine capable of producing realistic product mockups without relying on Printify's built-in mockup generator.

Current scope:

Bella Canvas 3001 only.

After Bella Canvas 3001 reaches production quality, the engine will expand to additional product categories.

Quality comes before quantity.

===============================================================================
CURRENT PROJECT STATUS
===============================================================================

Sprint 1

Status:

COMPLETE

Core engine is operational.

Verified modules:

- compositor.py
- pipeline.py
- library.py
- cli.py
- batch.py
- server.py
- recolor.py
- prepare_base.py
- export_etsy.py

Regression tests passed.

===============================================================================
CALIBRATION PIPELINE
===============================================================================

Calibration pipeline completed successfully.

Calibration asset:

assets/base-library/kalibrasyon/bella-ref/

Generated files:

- base.png
- garment_mask.png
- print_mask.png
- displace.png
- shading.png
- meta.json
- _debug_mask.png

Pipeline successfully generated every required output.

publishable = false

Purpose:

Internal calibration only.

Never publish this asset.

===============================================================================
CLOTH SEGMENTATION
===============================================================================

Status:

FIXED

Issue:

u2net_cloth_seg returns vertically stacked outputs.

Correct output:

Band 0

Validation:

Garment coverage:

42.7%

Background leakage:

0%

Garment pixels detected:

100%

This issue is considered resolved.

===============================================================================
VALIDATED MODULES
===============================================================================

CLI

PASS

Batch

PASS

Library

PASS

Pipeline

PASS

Compositor

PASS

Render

PASS

Mask generation

PASS

Displacement

PASS

Shading

PASS

Meta generation

PASS

Color engine

PASS

===============================================================================
KNOWN ISSUES
===============================================================================

Legacy folders may still exist.

Example:

bella-canvas-3001/female-front-001

may contain incomplete assets.

These folders are legacy.

Ignore them unless explicitly fixing them.

Batch may still enumerate them.

This is expected.

Not considered an engine bug.

===============================================================================
CURRENT DEVELOPMENT POLICY
===============================================================================

Until Bella Canvas 3001 reaches production quality:

NO

- Printify integration work
- Mug support
- Hoodie support
- Cap support
- Phone case support
- New geometry
- Mesh warp
- Optimization
- Refactoring
- Architecture redesign

YES

- Bug fixes
- Pipeline validation
- Asset preparation
- Calibration
- Production-quality rendering
- Real photo validation

===============================================================================
BELLA CANVAS 3001 SOP
===============================================================================

When the real shirt arrives:

Step 1

Photograph shirt.

Requirements:

- side lighting
- high resolution
- minimum 2400px short side
- arms separated
- neutral background

↓

Step 2

auto_mask.py

↓

Step 3

calibrate_quad.py

↓

Step 4

prepare_base.py

↓

Step 5

verify_recolor.py

↓

Step 6

cli.py

↓

Step 7

batch.py

↓

Step 8

Visual QA

↓

Step 9

Approve production asset.

===============================================================================
DEFINITION OF DONE
===============================================================================

Bella Canvas 3001 is considered complete only if:

✓ base.png

✓ garment_mask.png

✓ print_mask.png

✓ displace.png

✓ shading.png

✓ meta.json

are successfully generated

AND

Render quality is production-ready

AND

Recolor verification passes

AND

Manual QA approves the asset

===============================================================================
WHEN HELPING
===============================================================================

Always assume this document is correct.

Never repeat completed work.

Never scan the repository without a clear reason.

Prefer modifying existing code instead of creating new systems.

Do not propose alternative architectures unless requested.

Focus only on the user's current task.

If repository inspection is truly necessary, explain WHY before doing it.

When the requested task is complete:

STOP.

Wait for the next task.

