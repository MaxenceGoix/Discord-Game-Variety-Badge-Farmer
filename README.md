# Discord Game Variety Badge Farmer & Quest Completer

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-blue?logo=windows&logoColor=white)
![GUI](https://img.shields.io/badge/GUI-Tkinter-green)
![Discord](https://img.shields.io/badge/Discord-Desktop-5865F2?logo=discord&logoColor=white)

A Windows desktop utility with a Tkinter interface that loads Discord's detectable-application catalog and launches lightweight placeholder processes using the executable names listed in that catalog.

It provides manual selection and timed batch operation. **It does not launch the actual games.** Whether Discord recognizes these placeholder processes or grants Quest progress or profile badges is not guaranteed.

> **Important:** Automating activity or attempting to simulate game execution may conflict with Discord's Terms of Service or Quest rules. Use this project at your own discretion. No badge, Quest completion, or account outcome is guaranteed.

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Project files](#project-files)
- [Installation](#installation)
- [Usage](#usage)
  - [Manual mode](#manual-mode)
  - [Automatic mode](#automatic-mode)
- [Configuration](#configuration)
- [Game catalog](#game-catalog)
- [Troubleshooting](#troubleshooting)
- [Limitations and disclaimer](#limitations-and-disclaimer)

## Features

- **Searchable catalog:** filters entries by game name, application ID, and executable name.
- **Manual mode:** click a game entry to start its placeholder process; click the active entry again or use **Stop / Clear** to stop it.
- **Automatic mode:** processes a chosen range of catalog entries in batches.
- **Batch controls:** configure the number of processes per batch, their launch delay, and how long each batch runs.
- **Progress and status:** view a running/offline indicator, progress bar, and timer.
- **Persistent settings:** stores UI settings in `config.json`.
- **Temporary executable setup:** creates files in `games/` using hard links when possible, falling back to file copies when hard linking fails.
- **Cleanup on exit:** attempts to stop child processes and remove the generated `games/` directory when the application closes.

## How it works

1. The application reads `detectable.json` and keeps entries that contain a non-empty `executables` list.
2. It builds a searchable list using each entry's name, ID, and executable names.
3. When an entry is launched, the program selects a Windows-compatible executable path where possible. If none is found, it falls back to a sanitized game name with an `.exe` extension.
4. It creates a directory under `games/<application_id>/`, then links or copies the current Python GUI interpreter executable and detected Python/runtime DLLs under the selected executable filename.
5. It starts a small Python/Tkinter placeholder process. The process displays the selected game name in a minimized window; it is not the real game.
6. When a run ends or is stopped, the child process is terminated, with a force-kill fallback if it does not exit promptly.

Hard links generally avoid duplicating file contents on the same volume, but the fallback copy operation does use disk space. This project does not download or install the actual games.

## Requirements

- Windows 10 or Windows 11.
- A working Python installation. The script uses the Python executable and runtime DLLs from the environment in which it is launched.
- The standard-library Tkinter module, which is included with many Windows Python distributions.
- The official Discord desktop client if you want to observe Discord's activity detection. Activity visibility and recognition depend on Discord's own behavior and settings.

The project uses Python's standard library; no third-party Python packages are imported by the provided script.

## Project files

Keep these files in the same directory:

```text
Discord-Game-Variety-Badge-Farmer/
├── quest_completer.py
├── detectable.json
├── config.json          # created or updated by the application
├── games/               # generated at runtime; cleaned on normal exit
└── README.md
```

`config.json` can be generated automatically if it does not exist. `games/` is a runtime directory and should not need to be committed to version control.

## Installation

1. Install Python for Windows if it is not already installed. Make sure Tkinter is available.
2. Download or clone this repository.
3. Ensure `quest_completer.py` and `detectable.json` are in the same folder.
4. Open a terminal in that folder and run:

```bash
python quest_completer.py
```

If the `python` command is not available, use the Python launcher if installed:

```bash
py quest_completer.py
```

The application creates `games/` at startup and reads or creates `config.json`.

## Usage

### Manual mode

1. Search for a game by its name, application ID, or executable filename.
2. Click an entry to launch its placeholder process.
3. The status indicator changes to **Running** while the process is active.
4. Click the active entry again or select **Stop / Clear** to stop it.
5. To stop a manual session automatically, enable **Auto-stop manual game after 'Run Time'**. The selected runtime and unit determine the timeout.

The displayed activity is based on a placeholder process, not on the actual game being played.

### Automatic mode

1. Set **Start Iteration** and **End Iteration** to the inclusive range of catalog entries to process. The list is numbered starting at `1`.
2. Set **Run Time** and choose `minutes` or `seconds`.
3. Set **Increment** to the number of placeholder processes started in each batch.
4. Set **Increment Delay (s)** to the pause between launches within a batch.
5. Click **Start Auto**.
6. Click **Abort Auto** to request that the current automatic run stop.

The application runs one batch at a time. It starts up to `Increment` processes, waits for the configured duration, stops that batch, and then continues to the next batch. The last batch can contain fewer processes than the configured increment.

Large increments can start many processes at once and may increase resource use. Start with conservative values.

## Configuration

The application reads and writes `config.json`. If a key is missing or the file cannot be parsed, the application uses defaults for the corresponding settings and writes the resulting configuration.

| Key | Type | Default in the script | Description |
|---|---|---:|---|
| `start_iteration` | Integer | `1` | First catalog entry for automatic mode; numbering starts at 1. |
| `end_iteration` | Integer | Number of loaded games | Last catalog entry for automatic mode. |
| `run_time` | Integer | `15` | Duration for a manual auto-stop or each automatic batch. |
| `runtime_unit` | String | `"minutes"` | Runtime unit: `"minutes"` or `"seconds"`. |
| `increment` | Integer | `1` | Number of placeholder processes launched per automatic batch. |
| `increment_delay` | Number | `1.0` | Delay in seconds between launches within a batch. |
| `manual_auto_stop` | Boolean | `false` | Enables the manual session timeout. |

The `config.json` included with your project may contain different saved values from these defaults. The application preserves valid saved settings.

Example configuration:

```json
{
    "start_iteration": 1,
    "end_iteration": 10444,
    "run_time": 15,
    "runtime_unit": "minutes",
    "increment": 1,
    "increment_delay": 1.0,
    "manual_auto_stop": false
}
```

## Game catalog

`detectable.json` is a local JSON snapshot of Discord's detectable-application data. The script does not fetch updates from the network; it reads the local file supplied with the project.

The supplied catalog contains **23,968 records**, of which **10,444** have a non-empty `executables` list and are therefore loaded by the application. These counts describe the supplied file and can change if the catalog is replaced.

The script uses fields such as `id`, `name`, and `executables`. It prefers executable entries whose `os` value indicates Windows, then falls back to other executable entries if no Windows-compatible entry is available.

## Troubleshooting

### The application says `detectable.json` is missing

Place `detectable.json` in the same directory as `quest_completer.py`, then restart the application.

### The JSON catalog cannot be loaded

Make sure `detectable.json` is valid JSON and has not been truncated or edited incorrectly. Use the complete catalog file.

### A Python DLL error appears

The script looks for Python and Visual C runtime DLLs in the active Python installation's directories and links or copies the files it finds. Confirm that Python is correctly installed and that you are launching the script with the intended Python interpreter. DLL discovery can vary by Python distribution and installation layout.

### Discord does not show an activity

This tool launches a placeholder process rather than the actual game. Discord may not recognize it, display it, or treat it as valid Quest activity. Check Discord's activity-privacy settings, but note that changing those settings cannot guarantee recognition or Quest progress.

### The application closes unexpectedly or leaves files behind

Close the application normally when possible so its shutdown handler can stop child processes and remove `games/`. If the process is forcibly terminated or Windows shuts down unexpectedly, cleanup may not run; after confirming that the application and its child processes have stopped, you can remove the generated `games/` directory manually.

## Limitations and disclaimer

- This is a Windows-oriented utility and has not been documented here as tested on every Windows or Python configuration.
- It launches placeholder Python processes, not the actual games.
- Discord may change its activity detection, detectable-game catalog, or Quest requirements at any time.
- The catalog is a local snapshot and is not automatically synchronized by the script.
- Hard links may not be available in every environment; the script falls back to copying files, which can consume disk space.
- No guarantee is made that this software will complete a Quest, unlock a badge, or avoid account restrictions.
- Use of this software may be inconsistent with Discord's Terms of Service or the rules of individual Quests. You are responsible for reviewing and following the applicable terms.

## AI assistance

Parts of this project or its documentation may have been created with assistance from generative AI tools. This statement does not imply that the code has been independently audited or comprehensively tested.
