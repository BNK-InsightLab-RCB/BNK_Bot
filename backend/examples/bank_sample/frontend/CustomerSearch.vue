<template>
  <section>
    <h1>고객조회</h1>
    <form>
      <label>
        고객번호
        <input v-model="form.customerNo" name="customerNo" />
      </label>
      <button type="button" @click="searchCustomer">조회</button>
      <button type="button" @click="saveCustomer">저장</button>
    </form>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";

const screenId = "CUST_001";
const screenName = "고객조회";
const menuId = "MENU_CUSTOMER_SEARCH";

const form = {
  customerNo: "",
  customerName: "",
  status: "",
};

function searchCustomer() {
  if (!form.customerNo) {
    alert("고객번호를 입력하세요.");
    return;
  }

  return axios.get("/api/customer/search", {
    params: { customerNo: form.customerNo },
  });
}

function saveCustomer() {
  if (!form.customerNo) {
    alert("고객번호를 입력하세요.");
    return;
  }

  if (form.status === "CLOSED") {
    alert("해지 고객은 수정할 수 없습니다.");
    return;
  }

  return axios.post("/api/customer/save", form);
}
</script>
