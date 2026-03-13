"""
Face Matching Service using DeepFace
Compares facial features between two images (selfie vs ID document)
Includes face extraction, cropping, and quality validation
"""

import logging
import io
import numpy as np
from typing import Tuple, Dict, Any, List, Optional
from decimal import Decimal
import requests
from deepface import DeepFace
from PIL import Image

logger = logging.getLogger(__name__)

class FaceMatchingService:
    """
    Service for face verification using DeepFace.
    Compares selfie with ID document to verify identity.
    
    Features:
    - Detects faces using RetinaFace (modern, accurate detector)
    - Extracts and crops face regions
    - Validates face quality before comparison
    - Compares using ArcFace model (fast & accurate)
    """
    
    # Face matching threshold (0-100)
    # Above this: APPROVED, Below: REJECTED
    FACE_MATCH_THRESHOLD = 80
    
    # Accepted face matching models
    MODELS = ["VGG-Face", "Facenet", "Facenet512", "OpenFace", "DeepFace", "ArcFace", "Dlib"]
    MODEL_CHOICE = "ArcFace"  # Most accurate and fast
    
    # Face quality thresholds
    MIN_FACE_SIZE = 50  # Minimum face bounding box dimension in pixels
    MAX_FACE_SIZE = None  # No maximum
    MIN_CONFIDENCE = 0.9  # Minimum detection confidence
    
    @staticmethod
    async def compare_faces(
        selfie_url: str,
        id_document_url: str
    ) -> Tuple[bool, Decimal, Dict[str, Any]]:
        """
        Compare two images for facial similarity.
        
        Process:
        1. Download images from URLs
        2. Extract faces from both images
        3. Validate face quality
        4. Crop face regions
        5. Compare faces using DeepFace.verify()
        
        Args:
            selfie_url: Cloudinary URL of selfie image
            id_document_url: Cloudinary URL of ID document image
        
        Returns:
            Tuple of (is_match, confidence_score, metadata)
            - is_match: bool - True if faces match above threshold
            - confidence_score: Decimal (0-100)
            - metadata: Dict with details
        
        Raises:
            Exception if images cannot be processed
        """
        try:
            logger.info(f"[FACE_MATCH] ========== STARTING FACE VERIFICATION ==========")
            logger.info(f"[FACE_MATCH] Selfie URL: {selfie_url[:50]}...")
            logger.info(f"[FACE_MATCH] ID Document URL: {id_document_url[:50]}...")
            
            # Step 1: Download images
            logger.info(f"[FACE_MATCH] Step 1: Downloading images...")
            selfie_image = await FaceMatchingService._download_image(selfie_url)
            id_image = await FaceMatchingService._download_image(id_document_url)
            logger.info(f"[FACE_MATCH]   ✓ Selfie: {selfie_image.shape}")
            logger.info(f"[FACE_MATCH]   ✓ ID Document: {id_image.shape}")
            
            # Step 2: Extract faces from both images
            logger.info(f"[FACE_MATCH] Step 2: Extracting face regions...")
            selfie_faces, selfie_meta = await FaceMatchingService._extract_face_regions(
                selfie_image, 
                "SELFIE"
            )
            id_faces, id_meta = await FaceMatchingService._extract_face_regions(
                id_image,
                "ID_DOCUMENT"
            )
            
            # Step 3: Validate that faces were detected
            logger.info(f"[FACE_MATCH] Step 3: Validating face detection...")
            if not selfie_faces:
                logger.warning("[FACE_MATCH]   ✗ No faces detected in selfie")
                return False, Decimal("0.00"), {
                    "error": "No face detected in selfie",
                    "selfie_faces_found": 0,
                    "id_faces_found": len(id_faces),
                    "selfie_metadata": selfie_meta,
                    "id_metadata": id_meta
                }
            
            if not id_faces:
                logger.warning("[FACE_MATCH]   ✗ No faces detected in ID document")
                return False, Decimal("0.00"), {
                    "error": "No face detected in ID document",
                    "selfie_faces_found": len(selfie_faces),
                    "id_faces_found": 0,
                    "selfie_metadata": selfie_meta,
                    "id_metadata": id_meta
                }
            
            logger.info(f"[FACE_MATCH]   ✓ Selfie faces found: {len(selfie_faces)}")
            logger.info(f"[FACE_MATCH]   ✓ ID Document faces found: {len(id_faces)}")
            
            # Step 4: Select best face from each image
            logger.info(f"[FACE_MATCH] Step 4: Selecting best face from each image...")
            selfie_face = selfie_faces[0]  # Use largest/most confident face
            id_face = id_faces[0]
            
            logger.info(f"[FACE_MATCH]   ✓ Selfie face size: {selfie_face.shape}")
            logger.info(f"[FACE_MATCH]   ✓ ID Document face size: {id_face.shape}")
            
            # Step 5: Perform face verification on cropped images
            logger.info(f"[FACE_MATCH] Step 5: Comparing faces with {FaceMatchingService.MODEL_CHOICE}...")
            
            result = DeepFace.verify(
                img1_path=selfie_face,
                img2_path=id_face,
                model_name=FaceMatchingService.MODEL_CHOICE,
                distance_metric="cosine",
                enforce_detection=False,  # Already extracted faces
                detector_backend="retinaface"
            )
            
            # Extract confidence score
            distance = result.get("distance", 1.0)
            confidence_score = max(0, (1 - distance) * 100)
            is_match = confidence_score >= FaceMatchingService.FACE_MATCH_THRESHOLD
            
            logger.info(f"[FACE_MATCH] Step 6: Verification Results")
            logger.info(f"[FACE_MATCH]   - Distance: {distance:.4f}")
            logger.info(f"[FACE_MATCH]   - Confidence: {confidence_score:.2f}%")
            logger.info(f"[FACE_MATCH]   - Threshold: {FaceMatchingService.FACE_MATCH_THRESHOLD}%")
            logger.info(f"[FACE_MATCH]   - Match: {'✓ YES' if is_match else '✗ NO'}")
            logger.info(f"[FACE_MATCH] ========== VERIFICATION COMPLETE ==========")
            
            return is_match, Decimal(str(round(confidence_score, 2))), {
                "distance": float(distance),
                "confidence_score": float(confidence_score),
                "threshold": FaceMatchingService.FACE_MATCH_THRESHOLD,
                "is_match": is_match,
                "model_used": FaceMatchingService.MODEL_CHOICE,
                "verified": result.get("verified", False),
                "selfie_faces_detected": len(selfie_faces),
                "id_faces_detected": len(id_faces),
                "selfie_face_quality": selfie_meta,
                "id_face_quality": id_meta
            }
        
        except Exception as e:
            logger.error(f"[FACE_MATCH] ✗ ERROR during verification: {str(e)}", exc_info=True)
            return False, Decimal("0.00"), {
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    @staticmethod
    async def _extract_face_regions(
        image: np.ndarray,
        image_type: str = "UNKNOWN"
    ) -> Tuple[List[np.ndarray], Dict[str, Any]]:
        """
        Extract face regions from image using DeepFace.
        
        Returns:
        - List of cropped face images (numpy arrays)
        - Metadata about detection (count, sizes, confidence)
        """
        try:
            logger.debug(f"[FACE_MATCH] Extracting faces from {image_type}...")
            
            # Extract faces using RetinaFace detector
            faces_data = DeepFace.extract_faces(
                img_path=image,
                detector_backend="retinaface",
                enforce_detection=False
            )
            
            if not faces_data:
                logger.warning(f"[FACE_MATCH] No faces detected in {image_type}")
                return [], {
                    "count": 0,
                    "message": "No faces detected"
                }
            
            logger.info(f"[FACE_MATCH] Found {len(faces_data)} face(s) in {image_type}")
            
            # Process detected faces
            cropped_faces = []
            face_sizes = []
            face_confidences = []
            
            for idx, face_data in enumerate(faces_data):
                # Get facial area coordinates
                facial_area = face_data.get("facial_area", {})
                x = int(facial_area.get("x", 0))
                y = int(facial_area.get("y", 0))
                w = int(facial_area.get("w", 0))
                h = int(facial_area.get("h", 0))
                
                # Get confidence if available
                confidence = face_data.get("confidence", 0.0)
                face_confidences.append(float(confidence))
                
                # Calculate face size
                face_size = min(w, h)
                face_sizes.append(face_size)
                
                logger.debug(
                    f"[FACE_MATCH]   Face {idx+1}: "
                    f"Position({x},{y}), Size({w}x{h}), Confidence({confidence:.2f})"
                )
                
                # Validate face size
                if face_size < FaceMatchingService.MIN_FACE_SIZE:
                    logger.warning(
                        f"[FACE_MATCH]   Face {idx+1} is too small ({face_size}px < {FaceMatchingService.MIN_FACE_SIZE}px)"
                    )
                    continue
                
                # Extract the cropped face from original image
                # Add small padding for better face matching
                padding = int(face_size * 0.1)  # 10% padding
                x_start = max(0, x - padding)
                y_start = max(0, y - padding)
                x_end = min(image.shape[1], x + w + padding)
                y_end = min(image.shape[0], y + h + padding)
                
                cropped_face = image[y_start:y_end, x_start:x_end]
                
                if cropped_face.size > 0:
                    cropped_faces.append(cropped_face)
                    logger.debug(f"[FACE_MATCH]   ✓ Face {idx+1} extracted: {cropped_face.shape}")
            
            # Sort by size (largest first) and return
            # This ensures we always use the largest/main face in the image
            if cropped_faces:
                # Create list of (size, face) tuples for sorting
                face_with_sizes = []
                for face, size in zip(cropped_faces, face_sizes):
                    face_with_sizes.append((size, face))
                
                # Sort by size (descending) - largest first
                sorted_faces = [
                    f for _, f in sorted(
                        face_with_sizes,
                        reverse=True,
                        key=lambda x: x[0]
                    )
                ]
                
                # Log which faces were selected
                sorted_sizes = sorted(face_sizes, reverse=True)
                logger.info(
                    f"[FACE_MATCH] Sorted faces by size (largest first): "
                    f"{sorted_sizes[:3]}px (showing top 3)"
                )
                if sorted_faces:
                    logger.info(
                        f"[FACE_MATCH] Using largest face: {sorted_sizes[0]}px "
                        f"from {len(sorted_faces)} total faces"
                    )
                
                metadata = {
                    "count": len(sorted_faces),
                    "sizes": face_sizes,
                    "sorted_sizes": sorted_sizes,
                    "confidences": face_confidences,
                    "message": f"Successfully extracted {len(sorted_faces)} face(s), sorted by size"
                }
                
                return sorted_faces, metadata
            else:
                return [], {
                    "count": 0,
                    "detected_but_invalid": len(faces_data),
                    "message": "Faces detected but none passed quality checks"
                }
        

        except Exception as e:
            logger.error(
                f"[FACE_MATCH] Error extracting faces from {image_type}: {str(e)}",
                exc_info=True
            )
            return [], {
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    @staticmethod
    async def _download_image(url: str) -> np.ndarray:
        """Download image from URL and convert to numpy array."""
        try:
            import time
            logger.info(f"[FACE_MATCH] [DOWNLOAD] Starting download from URL...")
            logger.info(f"[FACE_MATCH] [DOWNLOAD] URL: {url[:80]}...")
            
            start_time = time.time()
            response = requests.get(url, timeout=30)
            download_time = time.time() - start_time
            logger.info(f"[FACE_MATCH] [DOWNLOAD] Downloaded ({download_time:.2f}s, {len(response.content)} bytes)")
            
            response.raise_for_status()
            
            logger.info(f"[FACE_MATCH] [DOWNLOAD] Opening image with PIL...")
            image = Image.open(io.BytesIO(response.content))
            
            # Convert to RGB if needed
            if image.mode != 'RGB':
                logger.debug(f"[FACE_MATCH] [DOWNLOAD] Converting from {image.mode} to RGB")
                image = image.convert('RGB')
            
            logger.info(f"[FACE_MATCH] [DOWNLOAD] Converting to numpy array...")
            image_array = np.array(image)
            logger.info(f"[FACE_MATCH] [DOWNLOAD] ✓ Complete. Shape: {image_array.shape}")
            return image_array
        
        except Exception as e:
            logger.error(f"[FACE_MATCH] [DOWNLOAD] ✗ Failed: {str(e)}")
            raise
    
    @staticmethod
    def _crop_face_to_base64(cropped_face: np.ndarray) -> str:
        """
        Convert cropped face numpy array to base64 string.
        Useful for sending to frontend as data:image URI.
        """
        try:
            # Convert numpy array to PIL Image
            face_image = Image.fromarray(cropped_face.astype('uint8'))
            
            # Convert to bytes
            buffer = io.BytesIO()
            face_image.save(buffer, format='JPEG', quality=85)
            buffer.seek(0)
            
            # Encode to base64
            import base64
            base64_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            return f"data:image/jpeg;base64,{base64_str}"
        
        except Exception as e:
            logger.error(f"[FACE_MATCH] Failed to convert face to base64: {str(e)}")
            raise
    
    @staticmethod
    async def get_face_preview(
        selfie_url: str,
        id_document_url: str
    ) -> Dict[str, Any]:
        """
        Extract and return face previews for UI display.
        Returns base64 encoded images of detected faces.
        
        Used to show users what faces will be compared.
        """
        try:
            import time
            logger.info(f"[FACE_MATCH_PREVIEW] ========== START ==========")
            
            # Download images
            logger.info(f"[FACE_MATCH_PREVIEW] Step 1: Downloading images...")
            start_dl = time.time()
            selfie_image = await FaceMatchingService._download_image(selfie_url)
            id_image = await FaceMatchingService._download_image(id_document_url)
            dl_time = time.time() - start_dl
            logger.info(f"[FACE_MATCH_PREVIEW] Step 1: ✓ Downloaded ({dl_time:.2f}s)")
            
            # Extract faces
            logger.info(f"[FACE_MATCH_PREVIEW] Step 2: Extracting face regions...")
            start_extract = time.time()
            selfie_faces, selfie_meta = await FaceMatchingService._extract_face_regions(
                selfie_image,
                "SELFIE"
            )
            id_faces, id_meta = await FaceMatchingService._extract_face_regions(
                id_image,
                "ID_DOCUMENT"
            )
            extract_time = time.time() - start_extract
            logger.info(f"[FACE_MATCH_PREVIEW] Step 2: ✓ Extracted ({extract_time:.2f}s)")
            logger.info(f"[FACE_MATCH_PREVIEW]   - Selfie faces: {len(selfie_faces)}")
            logger.info(f"[FACE_MATCH_PREVIEW]   - ID faces: {len(id_faces)}")
            
            # Convert to base64 for display
            logger.info(f"[FACE_MATCH_PREVIEW] Step 3: Converting to base64...")
            start_b64 = time.time()
            preview_data = {
                "selfie": None,
                "id_document": None,
                "selfie_detected": len(selfie_faces) > 0,
                "id_detected": len(id_faces) > 0,
                "selfie_count": len(selfie_faces),
                "id_count": len(id_faces)
            }
            
            if selfie_faces:
                try:
                    logger.info(f"[FACE_MATCH_PREVIEW]   Converting selfie face...")
                    preview_data["selfie"] = FaceMatchingService._crop_face_to_base64(
                        selfie_faces[0]
                    )
                    logger.info(f"[FACE_MATCH_PREVIEW]   ✓ Selfie preview created")
                except Exception as e:
                    logger.warning(f"[FACE_MATCH_PREVIEW]   ✗ Failed to create selfie preview: {e}")
            
            if id_faces:
                try:
                    logger.info(f"[FACE_MATCH_PREVIEW]   Converting ID face...")
                    preview_data["id_document"] = FaceMatchingService._crop_face_to_base64(
                        id_faces[0]
                    )
                    logger.info(f"[FACE_MATCH_PREVIEW]   ✓ ID document preview created")
                except Exception as e:
                    logger.warning(f"[FACE_MATCH_PREVIEW]   ✗ Failed to create ID preview: {e}")
            
            b64_time = time.time() - start_b64
            logger.info(f"[FACE_MATCH_PREVIEW] Step 3: ✓ Converted ({b64_time:.2f}s)")
            
            total_time = time.time() - time.time()  # Will be negative but we want elapsed
            logger.info(f"[FACE_MATCH_PREVIEW] ========== END (SUCCESS) ==========")
            logger.info(f"[FACE_MATCH_PREVIEW] Selfie preview: {'✓' if preview_data['selfie'] else '✗'}")
            logger.info(f"[FACE_MATCH_PREVIEW] ID preview: {'✓' if preview_data['id_document'] else '✗'}")
            
            return preview_data
        
        except Exception as e:
            logger.error(f"[FACE_MATCH_PREVIEW] ========== END (ERROR) ==========")
            logger.error(f"[FACE_MATCH_PREVIEW] Error getting face previews: {str(e)}", exc_info=True)
            return {
                "selfie": None,
                "id_document": None,
                "selfie_detected": False,
                "id_detected": False,
                "error": str(e)
            }
    
    @staticmethod
    async def _has_face(image: np.ndarray) -> bool:
        """
        Check if image contains a detectable face.
        Returns True if at least one face is detected.
        
        [DEPRECATED] Use _extract_face_regions instead for more detailed info.
        """
        try:
            logger.debug("[FACE_MATCH] Checking for faces in image...")
            
            faces = DeepFace.extract_faces(
                img_path=image,
                detector_backend="retinaface",
                enforce_detection=False
            )
            
            has_face = len(faces) > 0
            logger.debug(f"[FACE_MATCH] Faces detected: {len(faces)}")
            
            return has_face
        
        except Exception as e:
            logger.warning(f"[FACE_MATCH] Error detecting faces: {str(e)}")
            return False
    
    @staticmethod
    def validate_image_for_face_detection(image: np.ndarray) -> Tuple[bool, str]:
        """
        Validate if image is suitable for face detection.
        
        Returns:
            Tuple of (is_valid, message)
        """
        try:
            if image is None or image.size == 0:
                return False, "Image is empty"
            
            if len(image.shape) < 2:
                return False, "Invalid image format"
            
            height, width = image.shape[:2]
            
            if height < 100 or width < 100:
                return False, "Image too small (minimum 100x100 pixels)"
            
            if height > 4000 or width > 4000:
                return False, "Image too large (maximum 4000x4000 pixels)"
            
            return True, "Image is valid"
        
        except Exception as e:
            logger.error(f"[FACE_MATCH] Error validating image: {str(e)}")
            return False, f"Validation error: {str(e)}"
