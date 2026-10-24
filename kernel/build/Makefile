# Out-of-tree build of ov7251.ko from ../backport/ov7251.c (ov7251.c here is a symlink to it).
ifneq ($(KERNELRELEASE),)
obj-m := ov7251.o
else
KDIR ?= /lib/modules/$(shell uname -r)/build
CHECKPATCH ?= /home/antoine/projects/media-committers/scripts/checkpatch.pl

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean

check:
	$(CHECKPATCH) --strict --max-line-length=80 --no-tree -f ../backport/ov7251.c

.PHONY: all clean check
endif
