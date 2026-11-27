"""Offline test for tools/ir-rotation-report.py on the Surface Book 2 DSDT (esteban, 28 Nov 2026), cut to the IR sensor's
Device block up to its SSDB (closing brace added); the rotation byte is 0 and the sensor clock 19.2 MHz, as measured on this machine."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("rot", Path(__file__).resolve().parents[1] / "tools" / "ir-rotation-report.py")
rot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rot)

SAMPLE = """
        Device (CAM3)
        {
            Name (_ADR, Zero)  // _ADR: Address
            Name (_HID, "INT347E")  // _HID: Hardware ID
            Name (_CID, "INT347E")  // _CID: Compatible ID
            Name (_DDN, "OV7251-CRDD")  // _DDN: DOS Device Name
            Method (_SUB, 0, NotSerialized)  // _SUB: Subsystem ID
            {
                Return (GCSM (0x03))
            }

            Name (_UID, "0")  // _UID: Unique ID
            Name (_DEP, Package (0x01)  // _DEP: Dependencies
            {
                SKC2, 
            })
            Name (_PR0, Package (0x01)  // _PR0: Power Resources for D0
            {
                CAMP, 
            })
            Name (_PLD, Package (0x01)  // _PLD: Physical Location of Device
            {
                ToPLD (
                    PLD_Revision           = 0x2,
                    PLD_IgnoreColor        = 0x1,
                    PLD_Red                = 0x0,
                    PLD_Green              = 0x0,
                    PLD_Blue               = 0x0,
                    PLD_Width              = 0x0,
                    PLD_Height             = 0x0,
                    PLD_UserVisible        = 0x1,
                    PLD_Dock               = 0x0,
                    PLD_Lid                = 0x0,
                    PLD_Panel              = "FRONT",
                    PLD_VerticalPosition   = "CENTER",
                    PLD_HorizontalPosition = "RIGHT",
                    PLD_Shape              = "VERTICALRECTANGLE",
                    PLD_GroupOrientation   = 0x0,
                    PLD_GroupToken         = 0x0,
                    PLD_GroupPosition      = 0x0,
                    PLD_Bay                = 0x0,
                    PLD_Ejectable          = 0x1,
                    PLD_EjectRequired      = 0x1,
                    PLD_CabinetNumber      = 0x0,
                    PLD_CardCageNumber     = 0x0,
                    PLD_Reference          = 0x0,
                    PLD_Rotation           = 0x0,
                    PLD_Order              = 0x0,
                    PLD_VerticalOffset     = 0xFFFF,
                    PLD_HorizontalOffset   = 0xFFFF)

            })
            Method (_CRS, 0, NotSerialized)  // _CRS: Current Resource Settings
            {
                Name (SBUF, ResourceTemplate ()
                {
                    I2cSerialBusV2 (0x0060, ControllerInitiated, 0x00061A80,
                        AddressingMode7Bit, "\\_SB.PCI0.I2C3",
                        0x00, ResourceConsumer, , Exclusive,
                        )
                })
                Return (SBUF) /* \_SB_.PCI0.I2C3.CAM3._CRS.SBUF */
            }

            Method (_STA, 0, NotSerialized)  // _STA: Status
            {
                If (CL02)
                {
                    Return (0x0F)
                }

                Return (Zero)
            }

            Method (SSDB, 0, NotSerialized)
            {
                Name (PAR, Buffer (0x6C)
                {
                    /* 0000 */  0x00, 0x20, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // . ......
                    /* 0008 */  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // ........
                    /* 0010 */  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // ........
                    /* 0018 */  0x00, 0x00, 0x00, 0x00, 0x02, 0x01, 0x00, 0x00,  // ........
                    /* 0020 */  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // ........
                    /* 0028 */  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // ........
                    /* 0030 */  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // ........
                    /* 0038 */  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // ........
                    /* 0040 */  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // ........
                    /* 0048 */  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // ........
                    /* 0050 */  0x09, 0x00, 0x02, 0x00, 0x00, 0x01, 0x00, 0xF8,  // ........
                    /* 0058 */  0x24, 0x01, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00,  // $.......
                    /* 0060 */  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // ........
                    /* 0068 */  0x00, 0x00, 0x00, 0x00                           // ....
                })
                Return (PAR) /* \_SB_.PCI0.I2C3.CAM3.SSDB.PAR_ */
            }
        }
"""


def test_book2_ssdb():
    devices = list(rot.device_blocks(rot.strip_comments(SAMPLE)))
    assert len(devices) == 1
    data = rot.ssdb_bytes(devices[0])
    assert data[rot.DEGREE] == 0
    assert int.from_bytes(data[rot.MCLK], "little") == 19_200_000
