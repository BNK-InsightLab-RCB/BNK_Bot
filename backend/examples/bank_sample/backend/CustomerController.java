package com.example.branch.customer;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class CustomerController {
    private final CustomerService customerService;

    public CustomerController(CustomerService customerService) {
        this.customerService = customerService;
    }

    @GetMapping("/api/customer/search")
    public ResponseEntity<CustomerDto> searchCustomer(@RequestParam String customerNo, User user) {
        CustomerDto customer = customerService.searchCustomer(customerNo, user);
        return ResponseEntity.ok(customer);
    }

    @PostMapping("/api/customer/save")
    public ResponseEntity<Void> saveCustomer(@RequestBody CustomerDto dto, User user) {
        customerService.saveCustomer(dto, user);
        return ResponseEntity.ok().build();
    }
}
