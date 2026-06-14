<template>
  <section>
    <h1>체크카드 재발급</h1>
    <label>카드번호 <input v-model="form.cardNo" /></label>
    <label>배송지 우편번호 <input v-model="form.zipCode" /></label>
    <label>배송지 주소 <input v-model="form.deliveryAddress" /></label>
    <button type="button" @click="requestCardReissue">재발급신청</button>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";

const screenId = "CARD_210";
const screenName = "체크카드 재발급";
const menuId = "MENU_CARD_REISSUE";

const form = {
  cardNo: "",
  zipCode: "",
  deliveryAddress: "",
};

function requestCardReissue() {
  if (!form.cardNo) {
    alert("카드번호를 입력하세요.");
    return;
  }
  if (!form.zipCode || !form.deliveryAddress) {
    alert("배송지 주소를 확인하세요.");
    return;
  }
  return axios.post("/api/ops/card/reissue", form);
}
</script>
