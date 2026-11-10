"""부재·자재 규격·도면·연결.

선체 블록은 판을 격자로 놓고 이웃 판끼리 맞대기 용접한다. 보강재·브라켓은 판에 필릿 용접하고,
블록 이음에서는 가장자리 판끼리 맞대기 용접한다. 배관은 계통마다 스풀을 사슬로 잇고 밸브를
사이에 끼우며, 서포트가 스풀을 받친다. 관통 계통의 스풀 일부는 관통 블록의 판을 지난다.

모듈: base(부재 묶음·규격) · hull(선체 블록) · piping(배관 계통) · assemble(전체 조립·블록 이음·관통).
"""

from .assemble import build_structure
from .base import VALVE_LABELS, VALVE_TYPES, Structure, ensure_plate_spec

__all__ = ["VALVE_LABELS", "VALVE_TYPES", "Structure", "build_structure", "ensure_plate_spec"]
