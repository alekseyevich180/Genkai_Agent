---
name: matcraft-kit
description: A modular Python framework for building and analyzing atomic structures with CLI tools for materials modelling.
when_to_use: Use when you need to build, modify, inspect, or analyze atomic structures.
entry: mckit -h
---

# MatCraft Toolkit (`mckit`)

Use this skill to streamline and automate materials modeling workflows. The framework is divided into two primary command categories:

### Operations (Build & Modify)

Tasks dedicated to creating and manipulating atomic structures.

* **Command:** `mckit operate -h`
* **Capabilities:** Building bulk crystals, generating surface slabs with precise termination control, applying structural modifications, etc.

### Observations (Inspect & Analyze)

Tasks dedicated to analyzing structural properties and verifying geometry.

* **Command:** `mckit observe -h`
* **Capabilities:** Calculating structural metrics, inspecting coordination environments, and running validation checks.

---

> **Critical Workflow Rule:** Always check the structure after any structural modification using:
> `mckit observe inspect [<structure_file>]`
> *Never rely solely on intuition—always verify structural integrity programmatically.*
