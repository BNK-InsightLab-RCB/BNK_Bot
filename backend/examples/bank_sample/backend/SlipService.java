package com.example.branch.slip;

import org.springframework.stereotype.Service;

@Service
public class SlipService {
    private final SlipMapper slipMapper;

    public SlipService(SlipMapper slipMapper) {
        this.slipMapper = slipMapper;
    }

    public void approveSlip(SlipDto dto, User user) {
        if (!user.hasRole("SLIP_APPROVE")) {
            throw new BizException("전표 승인 권한이 없습니다.");
        }

        if (!"READY".equals(dto.getStatus())) {
            throw new BizException("승인 가능한 전표 상태가 아닙니다.");
        }

        slipMapper.approveSlip(dto);
    }
}
