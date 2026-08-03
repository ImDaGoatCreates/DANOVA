import React, { useState } from "react";
import {
  View,
  TextInput,
  Button,
  Text,
  ScrollView,
  StyleSheet,
} from "react-native";

const NGROK_URL = "https://abcd1234.ngrok.io"; // <-- put your ngrok URL here
const API_KEY = "my-super-secret-key";         // <-- same key as in api_key.txt (or leave empty)

export default function App() {
  const [msg, setMsg] = useState("");
  const [history, setHistory] = useState([]);

  const send = async () => {
    if (!msg.trim()) return;
    const newHist = [...history, { role: "user", content: msg }];
    setHistory(newHist);
    setMsg("");

    try {
      const res = await fetch(`${NGROK_URL}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(API_KEY && { Authorization: `Bearer ${API_KEY}` }),
        },
        body: JSON.stringify({ messages: newHist }),
      });

      if (!res.ok) throw new Error((await res.json()).error || "Unknown error");

      const data = await res.json();
      setHistory([...newHist, { role: "assistant", content: data.reply }]);
    } catch (e) {
      console.error(e);
      setHistory([
        ...history,
        { role: "assistant", content: `Error: ${e.message}` },
      ]);
    }
  };

  return (
    <View style={styles.container}>
      <ScrollView style={{ flexGrow: 1 }}>
        {history.map((h, i) => (
          <Text key={i} style={h.role === "assistant" ? styles.assistant : styles.user}>
            <b>{h.role}:</b> {h.content}
          </Text>
        ))}
      </ScrollView>

      <TextInput
        value={msg}
        onChangeText={setMsg}
        placeholder="Ask something…"
        style={styles.input}
      />
      <Button title="Send" onPress={send} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 10 },
  input: { borderWidth: 1, marginVertical: 5, padding: 8 },
  assistant: { color: "blue", marginVertical: 2 },
  user: { color: "green", marginVertical: 2 },
});