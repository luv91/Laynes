# Lanes Project - Claude Instructions

  ## Documentation Convention

  ### Where to write design docs / readmes
  - ALL design docs, readmes, and notes go to:
    `../Lanes_Discussions_and_Notes/`
    (i.e. /Users/luv/Documents/GitHub/AI_enabled_chatbot/Lanes_Discussions_and_Notes/)
  - NEVER write .md documentation files directly to the lanes/ root
  - Only README.md is allowed in lanes/ root

  ### Naming convention
  - Format: `readme{NN}-{short-description}.md`
  - Sequential numbering, current highest is 24
  - Next new doc starts at 25
  - Examples:
    - readme25-section-232-copper-fix.md
    - readme26-ieepa-reciprocal-design.md

  ### Subfolder structure (create if needed)
  Lanes_Discussions_and_Notes/
    design/          # System design docs (301, 232, IEEPA, stacker logic)
    testing/         # Test case docs, validation results
    refactoring/     # Refactoring plans and completion notes
    phase-notes/     # Phase completion summaries

  ### Rules
  - NEVER overwrite existing files
  - Always check the highest readme number before creating a new one
  - Keep lanes/ root clean - code and config files only
