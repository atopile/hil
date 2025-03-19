# OS

## Raspberry Pi OS

TODO: Add reference information on exactly what Raspberry Pi OS version is used and what configuration is used.

### Installing `usbboot` on OSx

We've had issues with the official instructions at https://github.com/raspberrypi/usbboot

Alternative instructions worked for @napowderly: https://www.jeffgeerling.com/blog/2020/how-flash-raspberry-pi-os-compute-module-4-emmc-usbboot

### Device Tree Configuration

Docs: https://github.com/raspberrypi/firmware/blob/master/boot/overlays/README

Configs are applied in config.txt:

`sudo nano /boot/firmware/config.txt`

To configure i2c, do something like: `dtoverlay=i2c1-pi5,baudrate=400000,pins_10_11`
This depends on your hardware and there are separate device tree overlays for different Raspberry Pi models and each peripheral.

NOTE: the flag "pins_10_11" must be placed after the baudrate param. Dunno why, but do it otherwise it'll not boot.
