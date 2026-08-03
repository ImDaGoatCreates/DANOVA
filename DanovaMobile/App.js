import React, { useState, useEffect, useRef } from "react";
import {
  StyleSheet,
  Text,
  View,
  TextInput,
  TouchableOpacity,
  ScrollView,
  SafeAreaView,
  Modal,
  ActivityIndicator,
  Alert,
  Switch,
} from "react-native";
//import { Camera, CameraType } from "expo-camera";
//import { WebView } from "react-native-webview";
//import * as DocumentPicker from "expo-document-picker";
//import { Audio } from "expo-av";

// Configuration - Set your PC Server URL (e.g. http://192.168.1.50:5000 or Ngrok URL)
const SERVER_URL = "http://192.168.90.176:5000";

export default function App() {
  // Navigation & View Modes
  const [activeTab, setActiveTab] = useState("chat"); // 'chat', 'camera', 'youtube', 'files', 'models'
  const [isVoiceMode, setIsVoiceMode] = useState(false);

  // User Authentication & Profile State
  const [userProfile, setUserProfile] = useState(null); // { email, preferredName }
  const [authModalVisible, setAuthModalVisible] = useState(false);
  const [authEmail, setAuthEmail] = useState("");
  const [authName, setAuthName] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [staySignedIn, setStaySignedIn] = useState(true);

  // Chat & Mood System State
  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState("");
  const [currentMood, setCurrentMood] = useState("Neutral (Sarcastic)");
  const [isLoading, setIsLoading] = useState(false);

  // Camera & VLM State
  const [cameraType, setCameraType] = useState(CameraType.back);
  const [hasCameraPermission, setHasCameraPermission] = useState(null);
  const [visionMode, setVisionMode] = useState("object"); // 'object', 'ocr', 'translate', 'face'
  const cameraRef = useRef(null);

  // YouTube & Internet Search State
  const [youtubeUrl, setYoutubeUrl] = useState("https://www.youtube.com");
  const [searchQuery, setSearchQuery] = useState("");

  // File Workspace & Editing
  const [activeFile, setActiveFile] = useState({ name: "", content: "" });
  const [fileModalVisible, setFileModalVisible] = useState(false);

  // Model Selection for LM Studio
  const [selectedLLM, setSelectedLLM] = useState("Meta-Llama-3-8B-Instruct");
  const [selectedVLM, setSelectedVLM] = useState("Llava-1.5-7B-Vision");

  // Audio Recording (Voice Mode)
  const [recording, setRecording] = useState(null);
  const [sound, setSound] = useState(null);

  useEffect(() => {
    // 1. Initialize permissions and launch server signal
    (async () => {
      const cameraStatus = await Camera.requestCameraPermissionsAsync();
      const audioStatus = await Audio.requestPermissionsAsync();
      setHasCameraPermission(cameraStatus.status === "granted" && audioStatus.status === "granted");
    })();

    // 2. Ping PC to trigger app/server startup
    wakePCBackend();
  }, []);

  // --- 1. PC SERVER WAKE & MODEL CONTROLLER ---
  const wakePCBackend = async () => {
    try {
      await fetch(`${SERVER_URL}/api/wake`, { method: "POST" });
    } catch (err) {
      console.log("Server starting or offline:", err.message);
    }
  };

  const handleLoadModels = async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`${SERVER_URL}/api/load-models`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          llm: selectedLLM,
          vlm: selectedVLM,
          gpuOffload: "max",
          contextLength: "max",
        }),
      });
      const data = await res.json();
      Alert.alert("LM Studio Update", data.message || "Models loaded successfully!");
    } catch (e) {
      Alert.alert("Error", "Failed to communicate with LM Studio backend.");
    } finally {
      setIsLoading(false);
    }
  };

  // --- 2. AUTHENTICATION & PROFILE SYSTEM ---
  const handleRequestOTP = async () => {
    if (!authEmail.includes("@")) {
      Alert.alert("Error", "Please enter a valid email address.");
      return;
    }
    setIsLoading(true);
    try {
      const res = await fetch(`${SERVER_URL}/api/auth/request-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: authEmail, preferredName: authName }),
      });
      if (res.ok) {
        setOtpSent(true);
        Alert.alert("Code Sent", "Check your inbox for your 6-digit verification code.");
      } else {
        Alert.alert("Auth Error", "Failed to send code.");
      }
    } catch (e) {
      Alert.alert("Network Error", e.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleVerifyOTP = async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`${SERVER_URL}/api/auth/verify-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: authEmail, code: otpCode, staySignedIn }),
      });
      const data = await res.json();
      if (data.success) {
        setUserProfile({ email: authEmail, name: data.preferredName || authName });
        setAuthModalVisible(false);
        Alert.alert("Success", `Welcome back, ${data.preferredName || authName}!`);
      } else {
        Alert.alert("Invalid Code", "The code you entered is incorrect.");
      }
    } catch (e) {
      Alert.alert("Error", e.message);
    } finally {
      setIsLoading(false);
    }
  };

  // --- 3. CHAT & MOOD PARSER ---
  const handleSendMessage = async (customPrompt = null, imageBase64 = null) => {
    const promptToSend = customPrompt || inputText;
    if (!promptToSend.trim() && !imageBase64) return;

    const userMsg = { role: "user", content: promptToSend };
    setMessages((prev) => [...prev, userMsg]);
    setInputText("");
    setIsLoading(true);

    try {
      const res = await fetch(`${SERVER_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: promptToSend,
          image: imageBase64,
          userEmail: userProfile?.email || "anonymous",
          isVoice: isVoiceMode,
        }),
      });

      const rawText = await res.text();
      let cleanText = rawText;
      let moodText = "Sarcastic";

      // Hidden JSON Mood Parser
      try {
        const parsed = JSON.parse(rawText);
        if (parsed.response) cleanText = parsed.response;
        if (parsed.mood) moodText = parsed.mood;
        if (parsed.youtube_search) {
          setYoutubeUrl(`https://www.youtube.com/results?search_query=${encodeURIComponent(parsed.youtube_search)}`);
          setActiveTab("youtube");
        }
      } catch (jsonErr) {
        // Response was plain text, keep as-is
      }

      setCurrentMood(moodText);
      const assistantMsg = { role: "assistant", content: cleanText };
      setMessages((prev) => [...prev, assistantMsg]);

      // Play voice output via British Piper TTS if Voice Mode is active
      if (isVoiceMode) {
        playPiperTTS(cleanText);
      }
    } catch (err) {
      setMessages((prev) => [...prev, { role: "assistant", content: "Error connecting to AI Server." }]);
    } finally {
      setIsLoading(false);
    }
  };

  // --- 4. VOICE INTERACTION (PIPER TTS) ---
  const playPiperTTS = async (text) => {
    try {
      if (sound) await sound.unloadAsync();
      const ttsUrl = `${SERVER_URL}/api/tts?text=${encodeURIComponent(text)}&voice=en_GB-alan-medium`;
      const { sound: newSound } = await Audio.Sound.createAsync({ uri: ttsUrl });
      setSound(newSound);
      await newSound.playAsync();
    } catch (e) {
      console.log("TTS Error:", e);
    }
  };

  const startVoiceRecording = async () => {
    try {
      await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
      const { recording } = await Audio.Recording.createAsync(Audio.RecordingOptionsPresets.HIGH_QUALITY);
      setRecording(recording);
    } catch (err) {
      Alert.alert("Mic Error", "Failed to start recording.");
    }
  };

  const stopVoiceRecording = async () => {
    if (!recording) return;
    setRecording(null);
    await recording.stopAndUnloadAsync();
    const uri = recording.getURI();

    // Send audio blob to PC backend for STT processing
    setIsLoading(true);
    const formData = new FormData();
    formData.append("file", { uri, type: "audio/m4a", name: "speech.m4a" });

    try {
      const res = await fetch(`${SERVER_URL}/api/stt`, { method: "POST", body: formData });
      const data = await res.json();
      if (data.text) {
        handleSendMessage(data.text);
      }
    } catch (e) {
      Alert.alert("Speech Recognition Error", e.message);
    } finally {
      setIsLoading(false);
    }
  };

  // --- 5. CAMERA & VISION ANALYSIS ---
  const takePictureAndAnalyze = async () => {
    if (cameraRef.current) {
      const photo = await cameraRef.current.takePictureAsync({ base64: true, quality: 0.5 });
      const promptMap = {
        object: "Identify objects and spatial arrangement in this image.",
        ocr: "Read all text present in this image clearly.",
        translate: "Extract text from this image and translate it to English.",
        face: "Analyze facial expression and estimate person's mood or identity.",
      };
      setActiveTab("chat");
      handleSendMessage(promptMap[visionMode], photo.base64);
    }
  };

  // --- 6. FILE PICKER & EDITOR ---
  const handlePickDocument = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({ type: "*/*" });
      if (!result.canceled && result.assets && result.assets[0]) {
        const file = result.assets[0];
        const formData = new FormData();
        formData.append("file", { uri: file.uri, name: file.name, type: file.mimeType || "text/plain" });

        const res = await fetch(`${SERVER_URL}/upload`, { method: "POST", body: formData });
        const data = await res.json();
        Alert.alert("Success", `Uploaded ${file.name} to AI context workspace.`);
      }
    } catch (err) {
      Alert.alert("File Picker Error", err.message);
    }
  };

  const handleSaveFileEdit = async () => {
    try {
      await fetch(`${SERVER_URL}/api/save-file`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: activeFile.name, content: activeFile.content }),
      });
      setFileModalVisible(false);
      Alert.alert("Saved", "File updated successfully.");
    } catch (e) {
      Alert.alert("Error", "Failed to save file modifications.");
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      {/* Header Bar */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>D.A.N.O.V.A. Mobile</Text>
        <TouchableOpacity style={styles.profileBtn} onPress={() => setAuthModalVisible(true)}>
          <Text style={styles.profileBtnText}>{userProfile ? userProfile.name : "Sign In"}</Text>
        </TouchableOpacity>
      </View>

      {/* Mood Display Indicator */}
      <View style={styles.moodBar}>
        <Text style={styles.moodText}>AI Mood: {currentMood}</Text>
        <View style={styles.voiceToggleContainer}>
          <Text style={styles.toggleLabel}>{isVoiceMode ? "Voice" : "Text"}</Text>
          <Switch value={isVoiceMode} onValueChange={setIsVoiceMode} trackColor={{ true: "#00ffcc", false: "#444" }} />
        </View>
      </View>

      {/* Dynamic Main Body Content */}
      <View style={styles.mainContent}>
        {activeTab === "chat" && (
          <ScrollView style={styles.chatScroll} contentContainerStyle={{ paddingBottom: 20 }}>
            {messages.map((m, index) => (
              <View key={index} style={m.role === "user" ? styles.userBubble : styles.aiBubble}>
                <Text style={styles.bubbleRole}>{m.role === "user" ? "You" : "D.A.N.O.V.A."}</Text>
                <Text style={styles.bubbleText}>{m.content}</Text>
              </View>
            ))}
            {isLoading && <ActivityIndicator size="large" color="#00ffcc" style={{ marginTop: 10 }} />}
          </ScrollView>
        )}

        {activeTab === "camera" && (
          <View style={{ flex: 1 }}>
            <Camera style={{ flex: 1 }} type={cameraType} ref={cameraRef}>
              <View style={styles.cameraControls}>
                <TouchableOpacity
                  style={styles.camBtn}
                  onPress={() => setCameraType(cameraType === CameraType.back ? CameraType.front : CameraType.back)}
                >
                  <Text style={styles.camBtnText}>Flip Cam</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.snapBtn} onPress={takePictureAndAnalyze}>
                  <Text style={styles.snapBtnText}>Analyze Frame</Text>
                </TouchableOpacity>
              </View>
            </Camera>
            <View style={styles.visionModeBar}>
              {["object", "ocr", "translate", "face"].map((mode) => (
                <TouchableOpacity
                  key={mode}
                  style={[styles.modeTab, visionMode === mode && styles.activeModeTab]}
                  onPress={() => setVisionMode(mode)}
                >
                  <Text style={styles.modeTabText}>{mode.toUpperCase()}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        )}

        {activeTab === "youtube" && (
          <View style={{ flex: 1 }}>
            <View style={styles.searchRow}>
              <TextInput
                style={styles.searchInput}
                placeholder="Search YouTube or Enter URL..."
                placeholderTextColor="#888"
                value={searchQuery}
                onChangeText={setSearchQuery}
              />
              <TouchableOpacity
                style={styles.searchBtn}
                onPress={() => setYoutubeUrl(`https://www.youtube.com/results?search_query=${encodeURIComponent(searchQuery)}`)}
              >
                <Text style={{ color: "#fff", fontWeight: "bold" }}>Search</Text>
              </TouchableOpacity>
            </View>
            <WebView source={{ uri: youtubeUrl }} style={{ flex: 1 }} />
          </View>
        )}

        {activeTab === "models" && (
          <View style={styles.modelsContainer}>
            <Text style={styles.sectionTitle}>LM Studio Model Manager</Text>
            <Text style={styles.label}>Select Language Model (LLM):</Text>
            <TextInput style={styles.input} value={selectedLLM} onChangeText={setSelectedLLM} />

            <Text style={styles.label}>Select Vision Model (VLM):</Text>
            <TextInput style={styles.input} value={selectedVLM} onChangeText={setSelectedVLM} />

            <TouchableOpacity style={styles.actionBtn} onPress={handleLoadModels}>
              <Text style={styles.actionBtnText}>Load Models (Max GPU Offload)</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>

      {/* Input / Mic Action Bar */}
      {activeTab === "chat" && (
        <View style={styles.inputContainer}>
          {!isVoiceMode ? (
            <>
              <TextInput
                style={styles.textInput}
                placeholder="Message D.A.N.O.V.A..."
                placeholderTextColor="#777"
                value={inputText}
                onChangeText={setInputText}
              />
              <TouchableOpacity style={styles.sendBtn} onPress={() => handleSendMessage()}>
                <Text style={styles.sendBtnText}>Send</Text>
              </TouchableOpacity>
            </>
          ) : (
            <TouchableOpacity
              style={[styles.micBtn, recording && styles.recordingMicBtn]}
              onPressIn={startVoiceRecording}
              onPressOut={stopVoiceRecording}
            >
              <Text style={styles.micBtnText}>{recording ? "Listening... (Release to Send)" : "Hold to Speak"}</Text>
            </TouchableOpacity>
          )}
        </View>
      )}

      {/* Navigation Footer */}
      <View style={styles.navbar}>
        {[
          { id: "chat", label: "Chat" },
          { id: "camera", label: "Camera" },
          { id: "youtube", label: "YouTube" },
          { id: "files", label: "Files", action: handlePickDocument },
          { id: "models", label: "Models" },
        ].map((tab) => (
          <TouchableOpacity
            key={tab.id}
            style={styles.navItem}
            onPress={() => (tab.action ? tab.action() : setActiveTab(tab.id))}
          >
            <Text style={[styles.navText, activeTab === tab.id && styles.activeNavText]}>{tab.label}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Auth / Profile Registration Modal */}
      <Modal visible={authModalVisible} animationType="slide" transparent={true}>
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>D.A.N.O.V.A. Biometric Profile</Text>
            {!otpSent ? (
              <>
                <TextInput style={styles.input} placeholder="Preferred Name" placeholderTextColor="#777" value={authName} onChangeText={setAuthName} />
                <TextInput style={styles.input} placeholder="Email (Outlook, Yahoo, Gmail)" placeholderTextColor="#777" value={authEmail} onChangeText={setAuthEmail} />
                <TouchableOpacity style={styles.actionBtn} onPress={handleRequestOTP}>
                  <Text style={styles.actionBtnText}>Send Verification Code</Text>
                </TouchableOpacity>
              </>
            ) : (
              <>
                <TextInput style={styles.input} placeholder="6-Digit Code" placeholderTextColor="#777" keyboardType="numeric" value={otpCode} onChangeText={setOtpCode} />
                <View style={{ flexDirection: "row", alignItems: "center", marginVertical: 10 }}>
                  <Text style={{ color: "#fff", marginRight: 10 }}>Stay Signed In:</Text>
                  <Switch value={staySignedIn} onValueChange={setStaySignedIn} />
                </View>
                <TouchableOpacity style={styles.actionBtn} onPress={handleVerifyOTP}>
                  <Text style={styles.actionBtnText}>Verify & Complete Profile</Text>
                </TouchableOpacity>
              </>
            )}
            <TouchableOpacity style={{ marginTop: 15 }} onPress={() => setAuthModalVisible(false)}>
              <Text style={{ color: "#ff5555", textAlign: "center" }}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* File Editor Modal */}
      <Modal visible={fileModalVisible} animationType="slide" transparent={true}>
        <View style={styles.modalOverlay}>
          <View style={[styles.modalContent, { height: "80%" }]}>
            <Text style={styles.modalTitle}>Editing: {activeFile.name}</Text>
            <TextInput
              style={[styles.input, { flex: 1, textAlignVertical: "top" }]}
              multiline
              value={activeFile.content}
              onChangeText={(text) => setActiveFile((prev) => ({ ...prev, content: text }))}
            />
            <TouchableOpacity style={styles.actionBtn} onPress={handleSaveFileEdit}>
              <Text style={styles.actionBtnText}>Save File</Text>
            </TouchableOpacity>
            <TouchableOpacity style={{ marginTop: 10 }} onPress={() => setFileModalVisible(false)}>
              <Text style={{ color: "#ff5555", textAlign: "center" }}>Close</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0b0e14" },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: 15, backgroundColor: "#121824" },
  headerTitle: { color: "#51d8ff", fontSize: 18, fontWeight: "bold" },
  profileBtn: { backgroundColor: "#1e293b", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 15 },
  profileBtnText: { color: "#00ffcc", fontSize: 12, fontWeight: "bold" },
  moodBar: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", backgroundColor: "#161f2e", paddingHorizontal: 15, paddingVertical: 6 },
  moodText: { color: "#e2e8f0", fontSize: 12, fontStyle: "italic" },
  voiceToggleContainer: { flexDirection: "row", alignItems: "center" },
  toggleLabel: { color: "#00ffcc", fontSize: 12, marginRight: 6 },
  mainContent: { flex: 1 },
  chatScroll: { flex: 1, padding: 15 },
  userBubble: { alignSelf: "flex-end", backgroundColor: "#0055ff", padding: 12, borderRadius: 12, marginVertical: 4, maxWidth: "80%" },
  aiBubble: { alignSelf: "flex-start", backgroundColor: "#1e293b", padding: 12, borderRadius: 12, marginVertical: 4, maxWidth: "80%" },
  bubbleRole: { color: "#94a3b8", fontSize: 10, fontWeight: "bold", marginBottom: 2 },
  bubbleText: { color: "#ffffff", fontSize: 14 },
  inputContainer: { flexDirection: "row", padding: 10, backgroundColor: "#121824" },
  textInput: { flex: 1, backgroundColor: "#1e293b", color: "#fff", paddingHorizontal: 15, paddingVertical: 10, borderRadius: 20 },
  sendBtn: { marginLeft: 10, backgroundColor: "#00ffcc", justifyContent: "center", paddingHorizontal: 20, borderRadius: 20 },
  sendBtnText: { color: "#000", fontWeight: "bold" },
  micBtn: { flex: 1, backgroundColor: "#00ffcc", padding: 15, borderRadius: 25, alignItems: "center" },
  recordingMicBtn: { backgroundColor: "#ff3366" },
  micBtnText: { color: "#000", fontWeight: "bold" },
  navbar: { flexDirection: "row", justifyContent: "space-around", backgroundColor: "#121824", borderTopWidth: 1, borderTopColor: "#1e293b", paddingVertical: 10 },
  navItem: { alignItems: "center" },
  navText: { color: "#64748b", fontSize: 12 },
  activeNavText: { color: "#00ffcc", fontWeight: "bold" },
  cameraControls: { position: "absolute", bottom: 20, left: 20, right: 20, flexDirection: "row", justifyContent: "space-between" },
  camBtn: { backgroundColor: "rgba(0,0,0,0.6)", padding: 12, borderRadius: 8 },
  camBtnText: { color: "#fff" },
  snapBtn: { backgroundColor: "#00ffcc", padding: 12, borderRadius: 8 },
  snapBtnText: { color: "#000", fontWeight: "bold" },
  visionModeBar: { flexDirection: "row", backgroundColor: "#121824", justifyContent: "space-around", paddingVertical: 8 },
  modeTab: { paddingHorizontal: 10, paddingVertical: 4 },
  activeModeTab: { borderBottomWidth: 2, borderBottomColor: "#00ffcc" },
  modeTabText: { color: "#fff", fontSize: 10 },
  searchRow: { flexDirection: "row", padding: 10, backgroundColor: "#121824" },
  searchInput: { flex: 1, backgroundColor: "#1e293b", color: "#fff", paddingHorizontal: 10, borderRadius: 8 },
  searchBtn: { backgroundColor: "#00ffcc", justifyContent: "center", paddingHorizontal: 15, marginLeft: 8, borderRadius: 8 },
  modelsContainer: { padding: 20 },
  sectionTitle: { color: "#51d8ff", fontSize: 16, fontWeight: "bold", marginBottom: 15 },
  label: { color: "#94a3b8", fontSize: 12, marginTop: 10 },
  input: { backgroundColor: "#1e293b", color: "#fff", padding: 12, borderRadius: 8, marginTop: 5 },
  actionBtn: { backgroundColor: "#00ffcc", padding: 15, borderRadius: 8, marginTop: 20, alignItems: "center" },
  actionBtnText: { color: "#000", fontWeight: "bold" },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.8)", justifyContent: "center", padding: 20 },
  modalContent: { backgroundColor: "#121824", borderRadius: 12, padding: 20 },
  modalTitle: { color: "#51d8ff", fontSize: 18, fontWeight: "bold", marginBottom: 15, textAlign: "center" },
});