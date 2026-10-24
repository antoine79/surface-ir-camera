# Out-of-tree builds of ov7251.ko and ipu-bridge.ko from ../backport/ (the .c files here are symlinks to it).
ifneq ($(KERNELRELEASE),)
obj-m := ov7251.o ipu-bridge.o
GCOV_PROFILE := $(if $(filter 1,$(GCOV)),y,n)  # make GCOV=1 on a CONFIG_GCOV_KERNEL kernel: tools/coverage.sh
else
KDIR ?= /lib/modules/$(shell uname -r)/build
CHECKPATCH ?= /home/antoine/projects/media-committers/scripts/checkpatch.pl

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean

check:
	-$(CHECKPATCH) --strict --max-line-length=80 --no-tree -f ../backport/ov7251.c
	$(CHECKPATCH) --strict --max-line-length=80 --no-tree -f ../backport/ipu-bridge.c

.PHONY: all clean check
endif
