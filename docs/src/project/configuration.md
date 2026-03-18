# Configuration

Placeholder --- to be written during Phase 4/6 implementation.

## Config Flow

Hamster uses a minimal config flow for initial setup.
No user input is required --- adding the integration creates a single config
entry.

The `manifest.json` declares `"single_config_entry": true` to prevent duplicate
instances.

## Options Flow

The options flow provides runtime configuration for:

- Per-service tristate control (Enabled/Dynamic/Disabled)
- Additional settings as features are added

Changes take effect without restarting HA (the options flow triggers a reload).
