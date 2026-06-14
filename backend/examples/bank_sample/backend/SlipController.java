package com.example.branch.slip;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class SlipController {
    private final SlipService slipService;

    public SlipController(SlipService slipService) {
        this.slipService = slipService;
    }

    @PostMapping("/api/slip/approve")
    public ResponseEntity<Void> approveSlip(@RequestBody SlipDto dto, User user) {
        slipService.approveSlip(dto, user);
        return ResponseEntity.ok().build();
    }
}
