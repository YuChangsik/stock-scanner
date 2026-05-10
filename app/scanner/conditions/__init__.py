from app.scanner.conditions.base import Condition
from app.scanner.conditions.volume_rank import VolumeRankCondition
from app.scanner.conditions.rsi import RsiCondition
from app.scanner.conditions.golden_cross import GoldenCrossCondition
from app.scanner.conditions.macd import MACDCondition
from app.scanner.conditions.macd_histogram import MacdHistogramCondition
from app.scanner.conditions.ma_above import MaAboveCondition
from app.scanner.conditions.ma_alignment import MaAlignmentCondition
from app.scanner.conditions.prev_high_breakout import PrevHighBreakoutCondition
from app.scanner.conditions.per import PerCondition
from app.scanner.conditions.pbr import PbrCondition
from app.scanner.conditions.sector import SectorCondition
from app.scanner.conditions.volume_surge import VolumeSurgeCondition
from app.scanner.conditions.atr import AtrCondition
from app.scanner.conditions.bollinger_band import BollingerBandCondition
from app.scanner.conditions.volume_recovery import VolumeRecoveryCondition
from app.scanner.conditions.obv_rising import ObvRisingCondition

CONDITION_REGISTRY: dict[str, type[Condition]] = {
    VolumeRankCondition.name:     VolumeRankCondition,
    RsiCondition.name:            RsiCondition,
    GoldenCrossCondition.name:    GoldenCrossCondition,
    MACDCondition.name:           MACDCondition,
    MacdHistogramCondition.name:  MacdHistogramCondition,
    MaAboveCondition.name:        MaAboveCondition,
    MaAlignmentCondition.name:    MaAlignmentCondition,
    PrevHighBreakoutCondition.name: PrevHighBreakoutCondition,
    PerCondition.name:            PerCondition,
    PbrCondition.name:            PbrCondition,
    SectorCondition.name:         SectorCondition,
    VolumeSurgeCondition.name:    VolumeSurgeCondition,
    AtrCondition.name:            AtrCondition,
    BollingerBandCondition.name:  BollingerBandCondition,
    VolumeRecoveryCondition.name: VolumeRecoveryCondition,
    ObvRisingCondition.name:      ObvRisingCondition,
}

__all__ = [
    "Condition",
    "VolumeRankCondition",
    "RsiCondition",
    "GoldenCrossCondition",
    "MACDCondition",
    "MacdHistogramCondition",
    "MaAboveCondition",
    "MaAlignmentCondition",
    "PrevHighBreakoutCondition",
    "PerCondition",
    "PbrCondition",
    "SectorCondition",
    "VolumeSurgeCondition",
    "AtrCondition",
    "BollingerBandCondition",
    "VolumeRecoveryCondition",
    "ObvRisingCondition",
    "CONDITION_REGISTRY",
]
