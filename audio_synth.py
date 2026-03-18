import numpy as np
import pygame
import time

class AudioSynth:
    """Sintetizzatore audio per creare una 'Sinfonia Rilassante' basata sul disegno."""
    
    def __init__(self):
        # Inizializza mixer di pygame con bassa latenza (buffer 512)
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
        pygame.init()
        pygame.mixer.init()
        
        self.sample_rate = 44100
        self.notes = []
        
        # Scala Pentatonica (C maggiore pentatonica) su 3 ottave.
        # È una scala estremamente rilassante e harmoniosa.
        base_freqs = [261.63, 293.66, 329.63, 392.00, 440.00] # C4, D4, E4, G4, A4
        freqs = []
        for octave in [0.5, 1.0, 2.0]: # Ottava bassa, media, alta
            for f in base_freqs:
                freqs.append(f * octave)
                
        # Ordiniamo in modo decrescente.
        # Sulla lavagna y=0 è in ALTAMENTE, y=44 è in BASSO.
        # Così in alto avremo le note acute, in basso le note gravi.
        self.freqs = sorted(freqs, reverse=True)
        
        # Pre-generiamo i Sound object di pygame
        print("[AUDIO] Generazione campioni audio in corso...")
        for f in self.freqs:
            self.notes.append(self._generate_sine_wave(f, duration=1.5))
            
        self.last_note_idx = -1
        self.last_play_time = 0
        self.min_time_between_notes = 0.25  # secondi
        
    def _generate_sine_wave(self, frequency, duration=1.0):
        """Genera una forma d'onda dal suono dolce (simile a campanella/flauto/synth)."""
        n_samples = int(self.sample_rate * duration)
        t = np.linspace(0, duration, n_samples, False)
        
        # Mix di armoniche per un suono più ricco e rilassante
        wave = 0.5 * np.sin(2 * np.pi * frequency * t)
        wave += 0.25 * np.sin(2 * np.pi * frequency * 2 * t)
        wave += 0.125 * np.sin(2 * np.pi * frequency * 3 * t)
        
        # Inviluppo ADSR super morbido per evitare "click"
        attack_time = 0.1
        release_time = duration - attack_time
        
        attack_samples = int(attack_time * self.sample_rate)
        release_samples = int(release_time * self.sample_rate)
        
        envelope = np.ones(n_samples)
        # Fade in (Attack) logaritmico/lineare
        envelope[:attack_samples] = np.linspace(0, 1, attack_samples)
        # Fade out (Release) lunghissimo
        envelope[-release_samples:] = np.linspace(1, 0, release_samples)
        
        wave = wave * envelope
        
        # Convertiamo a int16 per pygame (-32767 a 32767)
        audio_array = np.int16(wave * 32767)
        
        # Array stereo (2 colonne)
        stereo_array = np.column_stack((audio_array, audio_array))
        
        # Inseriamo nel wrapper Sound di Pygame
        sound = pygame.sndarray.make_sound(stereo_array)
        return sound

    def play_note(self, x: int, y: int, max_x: int, max_y: int, is_drawing: bool):
        """Suona una nota spaziale basata su coordinate (x, y)."""
        if not is_drawing:
            self.last_note_idx = -1
            return
            
        # 1. Troviamo quale nota suonare mappando la Y
        idx = int((y / max_y) * len(self.notes))
        idx = max(0, min(idx, len(self.notes) - 1))
        
        now = time.time()
        
        # Suona se cambiamo zona Y o se siamo fermi da un po' (per continuare la melodia)
        if idx != self.last_note_idx or (now - self.last_play_time > self.min_time_between_notes * 2.5):
            sound = self.notes[idx]
            
            # 2. Panning Spaziale: mappiamo la X al volume Destro e Sinistro
            # Se x=0 (sinistra), suona solo a sx. Se x=max (destra), suona solo a dx.
            pan = x / max(max_x, 1)
            left_vol = (1.0 - pan) * 0.5  # Max volume 0.5 per non assordare
            right_vol = pan * 0.5
            
            # Troviamo un canale libero e riproduciamo
            channel = pygame.mixer.find_channel()
            if channel:
                channel.set_volume(left_vol, right_vol)
                channel.play(sound)
                
            self.last_note_idx = idx
            self.last_play_time = now
