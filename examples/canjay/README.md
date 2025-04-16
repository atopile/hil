# CANJay

A CAN tool, built atop the atopile HIL framework.

## Development

`./config.txt` configures the RPi's kernel and device tree overlays

The links needs configuration:

```bash
sudo ip link set can1 type can bitrate 125000
```

And then bringing up:

```bash
sudo ip link set can1 up
```

**Note:** because they require privileged access, these commands aren't handled by `python-can`.

### Useful future references

- https://github.com/rm-hull/luma.oled
